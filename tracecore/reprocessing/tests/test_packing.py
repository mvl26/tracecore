import base64
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import frappe
from frappe.utils import get_fullname, getdate, now_datetime

from tracecore.core import client_time, extension, gs1
from tracecore.core import print as core_print
from tracecore.core.client_time import ClientTimestampError, parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import pack_label, packing
from tracecore.setup.label_templates import sample_pack_context
from tracecore.tests.factories import (
	make_assembly_record,
	make_ci_batch,
	make_employee,
	make_instrument,
	make_label_items,
	make_maintenance,
	make_pack_type,
	make_printer,
	make_roll,
	make_set_unit,
	make_t4_ready_set,
	next_free_test_cycle_id,
)
from tracecore.tests.utils import IsolatedTestCase, bru

# Pack (và Set Unit → Instrument Set Type, Printer) liên kết Item, Batch, Department, User, Employee của ERPNext/HRMS;
# site CI mới chưa chạy Setup Wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-004"
CYCLE_ID = re.compile(r"^CY-\d{6}-\d{4}$")


def _utc_now():
	"""`client_ts` như `parse_client_ts` trả: UTC, không múi giờ."""
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate(ready, **overrides):
	args = {
		"set_id": ready.set_id,
		"station": STATION,
		"confirmed": list(ready.instruments),
		"ci_batch": ready.ci_batch,
		"pack_type": ready.pack_type,
		"maint_actions": [],
		"client_ts": _utc_now(),
		**overrides,
	}
	return packing.generate(**args)


def _block(case, fn, *args, **kwargs):
	"""Gọi `fn` mong đợi BlockedError; trả Block để kiểm mã/nội dung."""
	with case.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


def _packs_of(set_id):
	return frappe.get_all("Pack", filters={"set_unit": set_id}, pluck="name")


def _gate(set_id, step, cycle_no=1):
	return frappe.db.get_value(
		"Step Gate Result",
		f"{set_id}-C{cycle_no}-{step}",
		["result", "redo_count", "ref_doctype", "ref_name", "station"],
		as_dict=True,
	)


def _unit(set_id):
	return frappe.db.get_value(
		"Set Unit", set_id, ["status", "active_cycle_id", "current_station"], as_dict=True
	)


def _cycle_codes():
	return frappe.db.count("Code Registry", {"prefix": "CY"})


def _series(key):
	# tabSeries không có cột modified nên không dùng get_value
	rows = frappe.db.sql("select `current` from `tabSeries` where `name` = %s", key)
	return rows[0][0] if rows else None


def _jobs_of(cycle_id):
	"""{tên Print Job: (status, error)} của nhãn gói `cycle_id`."""
	rows = frappe.get_all(
		"Print Job",
		filters={"ref_doctype": "Pack", "ref_name": cycle_id},
		fields=["name", "status", "error"],
	)
	return {str(row.name): (row.status, row.error) for row in rows}


def _capture_sql(fn, *args, **kwargs):
	"""Chạy `fn` và trả mọi câu SQL đã phát (chữ thường, gộp khoảng trắng)."""
	queries = []
	real_sql = frappe.db.sql

	def spy(query, *a, **kw):
		queries.append(" ".join(str(query).split()).lower())
		return real_sql(query, *a, **kw)

	with patch.object(frappe.db, "sql", spy):
		fn(*args, **kwargs)
	return queries


def _selects_on(queries, doctype):
	table = f"`tab{doctype}`".lower()
	return [q for q in queries if q.startswith("select") and table in q]


class TestGetContext(IsolatedTestCase):
	def test_get_context_returns_bom_gates_par_pack_types(self):
		ready = make_t4_ready_set()
		context = packing.get_context(ready.set_id, STATION)

		gates = {gate["step"]: gate["result"] for gate in context["gates"]}
		self.assertEqual(gates["T3"], "Pass")
		self.assertEqual(gates["T4"], "Pending")
		self.assertEqual(context["pack_types"][0]["item"], ready.pack_type)
		self.assertEqual(
			frappe.db.get_value("Instrument Set Type", ready.set_type, "default_pack_type"), ready.pack_type
		)
		self.assertEqual(context["printer"]["name"], ready.printer)
		self.assertEqual(context["label_type"], "VT-NHAN-HAP")
		self.assertEqual([line["instrument"] for line in context["bom"]], ["KC-01", "KC-02"])
		self.assertEqual(context["bom_version"], 1)
		self.assertEqual(context["maintenance"], [])
		self.assertEqual(context["par"]["state"], "ok")
		self.assertEqual(context["ci"], {"method": "Steam", "classes": ["5", "6"]})
		self.assertEqual(
			context["set"],
			{
				"set_id": ready.set_id,
				"set_type": ready.set_type,
				"set_name": frappe.db.get_value("Instrument Set Type", ready.set_type, "set_type_name"),
				"method": "Steam",
				"is_loaner": False,
				"status": "Processing",
				"cycles_used": 0,
				"max_cycles": 300,
				"department": None,
				"is_test": True,
			},
		)

	@bru("BRU-REP-009")
	def test_get_context_pack_types_carry_server_expected_expiry(self):
		# T4 hiển thị hạn dùng dự kiến do server tính (D4), không tính theo ngày của trình duyệt
		ready = make_t4_ready_set(shelf_life_days=10)  # loại bộ ghi đè ngắn hơn hạn loại gói (30 ngày)
		types = packing.get_context(ready.set_id, STATION)["pack_types"]
		self.assertTrue(types)
		for row in types:
			expected = packing.compute_expiry(getdate(), row["item"], ready.set_type)
			self.assertEqual(row["expected_expiry"], str(expected["expiry"]), msg=row["item"])
			self.assertEqual(row["days"], expected["days"], msg=row["item"])
		default = types[0]
		self.assertEqual(default["item"], ready.pack_type)
		self.assertEqual((default["shelf_life_days"], default["days"]), (30, 10))
		self.assertEqual(default["expected_expiry"], str(getdate() + timedelta(days=10)))

	def test_get_context_without_printer_names_the_label_type_to_load(self):
		ready = make_t4_ready_set("Plasma", with_printer=False)
		make_label_items()
		context = packing.get_context(ready.set_id, STATION)
		self.assertIsNone(context["printer"])
		self.assertEqual(context["label_type"], "VT-NHAN-PLASMA")

	@bru("BRU-FLOW-004")
	def test_get_context_rejects_when_t3_not_passed(self):
		ready = make_t4_ready_set()
		make_assembly_record(ready.set_id, "Fail")
		block = _block(self, packing.get_context, ready.set_id, STATION)
		self.assertEqual(block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(block.redo_step, "T3")

	def test_station_must_be_a_t4_station(self):
		ready = make_t4_ready_set()
		for station in ("TR-003", "ZONE-CLEAN", "TR-999", None):
			block = _block(self, packing.get_context, ready.set_id, station)
			self.assertEqual(block.code, "STATION_WRONG_STEP", msg=station)
			self.assertEqual(block.http_status, 422)
		self.assertEqual(_block(self, _generate, ready, station="TR-003").code, "STATION_WRONG_STEP")
		self.assertEqual(_packs_of(ready.set_id), [])

	def test_get_context_rejects_unknown_codes_and_missing_sets(self):
		self.assertEqual(_block(self, packing.get_context, "abc", STATION).code, "SCAN_INVALID")
		pack_code = _block(self, packing.get_context, "CY-261020-0001", STATION)
		self.assertEqual(pack_code.code, "SCAN_INVALID")
		self.assertIn("CY-261020-0001", pack_code.reason)
		missing = gs1.make_giai(gs1.configured_company_prefix(), "ZZZ999999")
		block = _block(self, packing.get_context, missing, STATION)
		self.assertEqual((block.code, block.http_status), ("SET_NOT_FOUND", 404))

	@bru("BRU-FLOW-002")
	def test_set_status_must_match_t4(self):
		# bộ mới (New, chưa vào chu trình) không vào được T4; trạng thái được báo trước mọi kiểm tra sau
		ready = make_t4_ready_set()
		fresh = frappe._dict(ready, set_id=make_set_unit(ready.set_type).name)
		for call in (lambda: packing.get_context(fresh.set_id, STATION), lambda: _generate(fresh)):
			block = _block(self, call)
			self.assertEqual((block.code, block.http_status), ("STATUS_INVALID_FOR_STATION", 409))
		self.assertEqual(_packs_of(fresh.set_id), [])

	def test_get_context_issues_no_locking_reads(self):
		# màn T4 chỉ hiển thị: không khóa Set Unit hay dòng cổng (chỉ generate khóa)
		ready = make_t4_ready_set()
		queries = _capture_sql(packing.get_context, ready.set_id, STATION)
		self.assertTrue(_selects_on(queries, "Set Unit"))
		self.assertTrue(_selects_on(queries, "Step Gate Result"))
		self.assertFalse([q for q in queries if "for update" in q])

	@bru("BRU-PAR-002")
	def test_get_context_runs_prechecks(self):
		ready = make_t4_ready_set(max_cycles=5)
		frappe.db.set_value("Set Unit", ready.set_id, "cycles_used", 5)
		self.assertEqual(_block(self, packing.get_context, ready.set_id, STATION).code, "PAR_EXCEEDED")


class TestGenerate(IsolatedTestCase):
	def test_generate_rejected_without_set_type_gtin(self):
		ready = make_t4_ready_set(gtin=None)
		self.assertEqual(
			_block(self, packing.get_context, ready.set_id, STATION).code, "SET_TYPE_GTIN_MISSING"
		)
		block = _block(self, _generate, ready)
		self.assertEqual((block.code, block.http_status), ("SET_TYPE_GTIN_MISSING", 409))
		self.assertEqual(_packs_of(ready.set_id), [])

	@bru("BRU-ID-002")
	def test_generate_creates_pack_with_all_fields(self):
		ready = make_t4_ready_set()
		client_ts = _utc_now()
		result = _generate(ready, client_ts=client_ts)
		cycle_id = result["pack"]["cycle_id"]
		self.assertRegex(cycle_id, CYCLE_ID)

		pack = frappe.get_doc("Pack", cycle_id)
		self.assertEqual(pack.docstatus, 1)
		self.assertEqual(pack.status, "Packed")
		self.assertEqual(pack.set_unit, ready.set_id)
		self.assertEqual(pack.set_type, ready.set_type)
		self.assertEqual(pack.cycle_no, 1)
		self.assertEqual(pack.method, "Steam")
		self.assertEqual(pack.bom_version, 1)
		self.assertEqual(pack.packed_by_user, frappe.session.user)
		self.assertEqual(pack.label_print_count, 1)
		self.assertEqual(pack.shelf_life_days_applied, 30)
		self.assertEqual(pack.shelf_life_source, "Pack Type")
		self.assertEqual(pack.pack_type, ready.pack_type)
		self.assertEqual(pack.ci_batch, ready.ci_batch)
		self.assertEqual(pack.station, STATION)
		self.assertEqual(pack.label_type, "VT-NHAN-HAP")
		self.assertEqual(pack.gtin, frappe.db.get_value("Instrument Set Type", ready.set_type, "gtin"))
		self.assertEqual(pack.gtin, ready.gtin)
		packed_at = frappe.utils.get_datetime(pack.packed_at)
		self.assertEqual(getdate(pack.expiry), packed_at.date() + timedelta(days=30))
		self.assertEqual(
			pack.barcode_payload,
			gs1.make_cycle_payload(pack.gtin, packed_at.date(), getdate(pack.expiry), cycle_id),
		)
		# R2: chứng từ T3 Đạt của chu trình hiện hành
		assembly = frappe.get_all(
			"Assembly Record", filters={"set_unit": ready.set_id, "docstatus": 1}, pluck="name"
		)
		self.assertEqual(pack.assembly, assembly[0])
		# client_ts lưu UTC (ADR-003), packed_at là giờ hệ thống (D13)
		self.assertEqual(frappe.utils.get_datetime(pack.client_ts), client_ts)
		self.assertLess(abs((packed_at - now_datetime()).total_seconds()), 60)
		self.assertEqual(
			[(row.instrument, row.qty) for row in pack.instruments_confirmed], [("KC-01", 2), ("KC-02", 1)]
		)
		self.assertEqual(pack.maint_done, [])

		registry = frappe.db.get_value(
			"Code Registry",
			cycle_id,
			["prefix", "ref_doctype", "ref_name", "status", "issued_at"],
			as_dict=True,
		)
		self.assertEqual(
			registry,
			{
				"prefix": "CY",
				"ref_doctype": "Pack",
				"ref_name": cycle_id,
				"status": "Active",
				"issued_at": STATION,
			},
		)

		summary = result["pack"]
		self.assertEqual(summary["set_id"], ready.set_id)
		self.assertEqual(summary["expiry"], str(getdate(pack.expiry)))
		self.assertEqual(summary["packer"], get_fullname(frappe.session.user))
		self.assertEqual(summary["pack_type_name"], frappe.db.get_value("Item", ready.pack_type, "item_name"))
		self.assertTrue(summary["is_test"])
		self.assertEqual(
			result["hri"], gs1.cycle_hri(pack.gtin, packed_at.date(), getdate(pack.expiry), cycle_id)
		)
		png = base64.b64decode(result["datamatrix_png_b64"])
		self.assertEqual(gs1.decode_datamatrix_png(png), pack.barcode_payload)

	def test_label_uses_gtin_issued_from_declared_prefix(self):
		# A-76: loại bộ tự cấp GTIN từ mã doanh nghiệp; nhãn Cycle ID và Pack lấy đúng GTIN đó, không dòng TEST
		frappe.db.set_single_value("TraceCore Settings", "gs1_company_prefix", "8930001")
		ready = make_t4_ready_set(gtin=None)
		gtin = frappe.db.get_value("Instrument Set Type", ready.set_type, "gtin")
		self.assertEqual(gtin[1:8], "8930001")
		pack = frappe.get_doc("Pack", _generate(ready)["pack"]["cycle_id"])
		self.assertEqual(pack.gtin, gtin)
		self.assertEqual(gs1.parse_scan(pack.barcode_payload)["gtin"], gtin)
		self.assertFalse(gs1.is_test_gtin(pack.gtin))

	@bru("BRU-FLOW-004")
	def test_generate_records_t4_pass_and_binds_cycle(self):
		ready = make_t4_ready_set()
		cycle_id = _generate(ready)["pack"]["cycle_id"]
		gate = _gate(ready.set_id, "T4")
		self.assertEqual(
			gate,
			{
				"result": "Pass",
				"redo_count": 0,
				"ref_doctype": "Pack",
				"ref_name": cycle_id,
				"station": STATION,
			},
		)
		unit = _unit(ready.set_id)
		self.assertEqual(unit.active_cycle_id, cycle_id)
		self.assertEqual(unit.current_station, STATION)
		self.assertEqual(unit.status, "Processing")

	@bru("BRU-ID-004")
	def test_second_generate_rejected_with_existing_cycle(self):
		ready = make_t4_ready_set()
		first = _generate(ready)["pack"]["cycle_id"]
		block = _block(self, _generate, ready)
		self.assertEqual((block.code, block.http_status), ("ACTIVE_CYCLE_EXISTS", 409))
		self.assertIn(first, block.reason)
		self.assertEqual(_packs_of(ready.set_id), [first])
		# get_context cũng chặn: bộ đã có Cycle ID hiệu lực
		self.assertEqual(_block(self, packing.get_context, ready.set_id, STATION).code, "ACTIVE_CYCLE_EXISTS")

	@bru("BRU-ID-004")
	def test_active_cycle_is_reported_before_t3_gate(self):
		# T3 làm lại sau khi đã có gói: cổng T3 Không đạt nhưng Cycle ID cũ vẫn hiệu lực → báo Cycle ID trước
		ready = make_t4_ready_set()
		first = _generate(ready)["pack"]["cycle_id"]
		make_assembly_record(ready.set_id, "Fail")
		block = _block(self, _generate, ready)
		self.assertEqual(block.code, "ACTIVE_CYCLE_EXISTS")
		self.assertIn(first, block.reason)
		packing.void(first, "Torn", STATION)
		self.assertEqual(_block(self, _generate, ready).code, "GATE_PREV_NOT_PASSED")

	@bru("BRU-REP-013")
	def test_incomplete_bom_rejected_and_rolled_back(self):
		ready = make_t4_ready_set()
		codes = _cycle_codes()
		series_key = f"CY-{now_datetime():%y%m%d}-"
		series = _series(series_key)
		block = _block(self, _generate, ready, confirmed=["KC-01"])
		self.assertEqual((block.code, block.http_status), ("BOM_INCOMPLETE", 422))
		self.assertEqual(block.items[0]["instrument"], "KC-02")
		self.assertEqual(len(block.items), 1)
		self.assertEqual(_packs_of(ready.set_id), [])
		self.assertEqual(_cycle_codes(), codes)
		self.assertEqual(_series(series_key), series)
		self.assertIsNone(_gate(ready.set_id, "T4"))

	@bru("BRU-REP-013")
	def test_empty_bom_blocks_generate(self):
		# loại bộ chưa khai báo BOM cho phiên bản hiện hành: không có gì để đối chiếu thì không sinh Cycle ID
		ready = make_t4_ready_set(bom=())
		block = _block(self, _generate, ready)
		self.assertEqual((block.code, block.http_status), ("BOM_INCOMPLETE", 422))
		self.assertIn(ready.set_type, block.reason)
		self.assertIn("1", block.reason)
		self.assertIn("R02", block.action)
		self.assertEqual(_packs_of(ready.set_id), [])

	@bru("BRU-REP-013")
	def test_failure_after_writes_rolls_back_everything(self):
		"""Lỗi ở bước sau cùng (hook sau khi sinh) phải hoàn tác Pack, mã, series, cổng, Set Unit, bảo dưỡng."""
		make_instrument("KC-31", interval=10)
		ready = make_t4_ready_set(bom=(("KC-31", 1),))
		make_maintenance(ready.set_id, "KC-31", cycles_since=10)
		codes = _cycle_codes()
		series_key = f"CY-{now_datetime():%y%m%d}-"
		series = _series(series_key)
		jobs = frappe.db.count("Print Job")
		pack_audits = frappe.db.count("Audit Log", {"ref_doctype": "Pack"})
		real_run = extension.run

		def failing_run(hook, *args, **kwargs):
			results = real_run(hook, *args, **kwargs)
			if hook == "tracecore_after_cycle_id":
				raise BlockedError(Block("MAINT_OIL_LOT_REQUIRED", "title", "reason", "action"))
			return results

		with patch.object(extension, "run", failing_run):
			block = _block(self, _generate, ready, maint_actions=[{"instrument": "KC-31", "action": "Done"}])
		self.assertEqual(block.code, "MAINT_OIL_LOT_REQUIRED")
		self.assertEqual(_packs_of(ready.set_id), [])
		self.assertEqual(_cycle_codes(), codes)
		self.assertEqual(_series(series_key), series)
		self.assertIsNone(_gate(ready.set_id, "T4"))
		unit = _unit(ready.set_id)
		self.assertIsNone(unit.active_cycle_id)
		self.assertIsNone(unit.current_station)
		self.assertEqual(
			frappe.db.get_value(
				"Instrument Maintenance",
				{"set_unit": ready.set_id, "instrument": "KC-31"},
				"cycles_since_maint",
			),
			10,
		)
		self.assertEqual(frappe.db.count("Print Job"), jobs)
		self.assertEqual(frappe.db.count("Audit Log", {"ref_doctype": "Pack"}), pack_audits)

	def test_generate_reports_first_failing_check_in_order(self):
		ready = make_t4_ready_set()
		plasma_lot = make_ci_batch("Plasma")
		cases = (
			({"confirmed": ["KC-01"], "ci_batch": plasma_lot, "pack_type": "NO-SUCH"}, "BOM_INCOMPLETE"),
			({"ci_batch": plasma_lot, "pack_type": "NO-SUCH"}, "CI_LOT_INVALID"),
			({"ci_batch": make_ci_batch("Steam", expiry_days=-1)}, "CI_LOT_EXPIRED"),
			({"pack_type": "NO-SUCH"}, "PACK_TYPE_INVALID"),
		)
		for overrides, code in cases:
			self.assertEqual(_block(self, _generate, ready, **overrides).code, code, msg=overrides)
		self.assertEqual(_packs_of(ready.set_id), [])

	@bru("BRU-PAR-002")
	def test_par_exceeded_blocks_generate(self):
		ready = make_t4_ready_set(max_cycles=5)
		frappe.db.set_value("Set Unit", ready.set_id, "cycles_used", 5)
		block = _block(self, _generate, ready)
		self.assertEqual((block.code, block.http_status), ("PAR_EXCEEDED", 409))
		self.assertEqual(_packs_of(ready.set_id), [])
		frappe.db.set_value("Set Unit", ready.set_id, "cycles_used", 4)
		self.assertRegex(_generate(ready)["pack"]["cycle_id"], CYCLE_ID)

	@bru("BRU-REP-014")
	def test_generate_applies_maintenance_actions(self):
		for code in ("KC-21", "KC-22"):
			make_instrument(code, interval=10)
		ready = make_t4_ready_set(bom=(("KC-21", 1), ("KC-22", 1), ("KC-23", 1)))
		make_maintenance(ready.set_id, "KC-21", cycles_since=10)
		make_maintenance(ready.set_id, "KC-22", cycles_since=11, deferred_count=1)

		block = _block(self, _generate, ready)
		self.assertEqual(block.code, "MAINT_ACTION_REQUIRED")
		self.assertEqual({item["instrument"] for item in block.items}, {"KC-21", "KC-22"})

		actions = [
			{"instrument": "KC-21", "action": "Done", "reason": "  "},
			{"instrument": "KC-22", "action": "Deferred", "reason": " Hết dầu "},
			{"instrument": "KC-23", "action": "Done"},  # chưa đến hạn: bỏ qua
		]
		cycle_id = _generate(ready, maint_actions=actions)["pack"]["cycle_id"]
		rows = frappe.get_doc("Pack", cycle_id).maint_done
		self.assertEqual(
			[(r.instrument, r.action, r.reason, r.oil_batch, r.cycles_at_action) for r in rows],
			[("KC-21", "Done", None, None, 10), ("KC-22", "Deferred", "Hết dầu", None, 11)],
		)
		counters = {
			row.instrument: (row.cycles_since_maint, row.deferred_count)
			for row in frappe.get_all(
				"Instrument Maintenance",
				filters={"set_unit": ready.set_id},
				fields=["instrument", "cycles_since_maint", "deferred_count"],
			)
		}
		self.assertEqual(counters, {"KC-21": (0, 0), "KC-22": (11, 2)})

	@bru("BRU-REP-011")
	def test_no_printer_for_method_keeps_cycle_id(self):
		ready = make_t4_ready_set("Plasma", with_printer=False)
		steam_label, _plasma_label = make_label_items()
		make_printer(STATION, steam_label)
		result = _generate(ready)
		cycle_id = result["pack"]["cycle_id"]
		printed = result["print"]
		self.assertEqual(printed["status"], "Waiting")
		self.assertIsNone(printed["printer"])
		self.assertIsNone(printed["zpl"])
		warning = printed["warning"]
		self.assertEqual(warning["code"], "NO_PRINTER_FOR_METHOD")
		self.assertTrue(warning["title"] and warning["action"])
		self.assertIn(STATION, warning["reason"])
		self.assertIn(cycle_id, warning["reason"])
		self.assertIn("VT-NHAN-PLASMA", warning["action"])
		self.assertIn("CN-", warning["action"])
		self.assertTrue(frappe.db.exists("Pack", cycle_id))
		self.assertIsNone(result["pack"]["label_type"])

		job = frappe.get_doc("Print Job", printed["print_job"])
		self.assertEqual((job.status, job.ref_doctype, job.ref_name), ("Waiting", "Pack", cycle_id))
		self.assertFalse(job.payload)
		data = frappe.parse_json(job.data)
		self.assertEqual((data["method"], data["label_object"]), ("Plasma", "Pack"))
		self.assertEqual(data["label_context"]["cycle_id"], cycle_id)

	def test_missing_label_template_waits_instead_of_failing(self):
		ready = make_t4_ready_set()
		frappe.db.set_value("Label Template", {"method": "Steam", "language": "ZPL"}, "is_active", 0)
		result = _generate(ready)
		printed = result["print"]
		self.assertEqual((printed["status"], printed["zpl"], printed["printer"]), ("Waiting", None, None))
		self.assertEqual(printed["warning"]["code"], "LABEL_TEMPLATE_MISSING")
		self.assertIn("ZPL", printed["warning"]["reason"])
		self.assertTrue(frappe.db.exists("Pack", result["pack"]["cycle_id"]))

	def test_label_render_error_waits_instead_of_failing(self):
		ready = make_t4_ready_set()
		messages = len(frappe.local.message_log)

		def broken(*args, **kwargs):
			frappe.throw("template exploded")

		with patch.object(core_print, "render", broken):
			result = _generate(ready)
		printed = result["print"]
		self.assertEqual((printed["status"], printed["zpl"]), ("Waiting", None))
		self.assertEqual(printed["warning"]["code"], "LABEL_RENDER_FAILED")
		self.assertIn("template exploded", printed["warning"]["reason"])
		self.assertTrue(frappe.db.exists("Pack", result["pack"]["cycle_id"]))
		# lỗi đã bắt không để lại msgprint cho kiosk
		self.assertEqual(len(frappe.local.message_log), messages)

	def test_generate_queues_label_on_matching_printer(self):
		ready = make_t4_ready_set()
		result = _generate(ready)
		cycle_id = result["pack"]["cycle_id"]
		printed = result["print"]
		self.assertEqual(printed["status"], "Queued")
		self.assertEqual(printed["printer"], ready.printer)
		self.assertIsNone(printed["warning"])
		self.assertTrue(printed["zpl"].startswith("^XA"))
		self.assertIn("_101" + ready.gtin, printed["zpl"])
		self.assertIn("^FDTEST^FS", printed["zpl"])
		job = frappe.get_doc("Print Job", printed["print_job"])
		self.assertEqual(
			(job.status, job.printer, job.ref_doctype, job.ref_name, job.payload, job.template),
			("Queued", ready.printer, "Pack", cycle_id, printed["zpl"], "Pack label - Steam"),
		)
		self.assertIsNone(job.reprint_reason)
		self.assertEqual(frappe.parse_json(job.data)["label_context"]["cycle_id"], cycle_id)

	def test_label_text_follows_printer_unicode_flag(self):
		name = "Bộ phẫu thuật chỉnh hình"
		ready = make_t4_ready_set(set_type_name=name)
		folded = _generate(ready)
		self.assertIn("Bo phau thuat chinh hinh", folded["print"]["zpl"])
		self.assertEqual(folded["pack"]["set_name"], name)
		job = frappe.get_doc("Print Job", folded["print"]["print_job"])
		self.assertEqual(frappe.parse_json(job.data)["label_context"]["set_name"], name)

		other = make_t4_ready_set(set_type_name=name, with_printer=False)
		frappe.db.set_value("Printer", ready.printer, "supports_unicode", 1)
		kept = _generate(other)
		self.assertIn(name, kept["print"]["zpl"])

	def test_generate_uses_local_date_from_client_ts(self):
		ready = make_t4_ready_set()
		client_ts = parse_client_ts("2026-10-21T00:30:00+07:00")
		with patch.object(client_time, "utc_now", return_value=client_ts):  # giờ server = giờ trạm (F1)
			result = _generate(ready, client_ts=client_ts)
		cycle_id = result["pack"]["cycle_id"]
		self.assertTrue(cycle_id.startswith("CY-261021-"), cycle_id)
		pack = frappe.get_doc("Pack", cycle_id)
		self.assertIn("11261021", pack.barcode_payload)
		self.assertEqual(frappe.utils.get_datetime(pack.packed_at), datetime(2026, 10, 21, 0, 30))
		self.assertEqual(frappe.utils.get_datetime(pack.client_ts), datetime(2026, 10, 20, 17, 30))
		self.assertEqual(getdate(pack.expiry), getdate("2026-11-20"))
		self.assertEqual(result["pack"]["packed_at"], "2026-10-21 00:30:00")

	def test_generate_rejects_station_clock_skew(self):
		# F1 (ADR-003): ngày trong Cycle ID, (11)/(17), hạn dùng và kiểm lô chỉ thị lấy từ client_ts, nên giờ trạm
		# lệch giờ server quá tc_client_ts_max_skew_seconds (mặc định 300 s) thì không sinh (400, không ghi gì)
		ready = make_t4_ready_set()
		server = _utc_now()
		for minutes in (6, -6):
			with self.subTest(minutes=minutes):
				with (
					patch.object(client_time, "utc_now", return_value=server),
					self.assertRaises(ClientTimestampError) as raised,
				):
					_generate(ready, client_ts=server + timedelta(minutes=minutes))
				self.assertEqual(raised.exception.http_status_code, 400)
				self.assertIn("6", str(raised.exception))
				self.assertIn("R10", str(raised.exception))
				self.assertEqual(_packs_of(ready.set_id), [])
				self.assertIsNone(_unit(ready.set_id).active_cycle_id)
				self.assertIsNone(_gate(ready.set_id, "T4"))
		with patch.object(client_time, "utc_now", return_value=server):
			result = _generate(ready, client_ts=server + timedelta(minutes=4))
		self.assertRegex(result["pack"]["cycle_id"], CYCLE_ID)

	def test_station_clock_skew_limit_from_site_config(self):
		ready = make_t4_ready_set()
		server = _utc_now()
		with (
			patch.dict(frappe.conf, {"tc_client_ts_max_skew_seconds": 60}),
			patch.object(client_time, "utc_now", return_value=server),
			self.assertRaises(ClientTimestampError),
		):
			_generate(ready, client_ts=server - timedelta(minutes=2))
		self.assertEqual(_packs_of(ready.set_id), [])

	def test_generate_locks_set_unit_before_reading_gates(self):
		ready = make_t4_ready_set()
		queries = _capture_sql(_generate, ready)
		unit_reads = _selects_on(queries, "Set Unit")
		gate_reads = _selects_on(queries, "Step Gate Result")
		self.assertIn("for update", unit_reads[0])
		self.assertTrue(gate_reads)
		self.assertFalse([q for q in gate_reads if "for update" not in q])
		self.assertLess(queries.index(unit_reads[0]), queries.index(gate_reads[0]))

	@bru("BRU-REP-009")
	def test_shelf_life_change_applies_to_new_packs_only(self):
		ready = make_t4_ready_set()
		first = _generate(ready)["pack"]["cycle_id"]
		first_expiry = frappe.db.get_value("Pack", first, "expiry")
		make_pack_type(shelf_life_days=20)  # cùng loại gói mặc định, hạn lưu mới
		packing.void(first, "Label Damaged", STATION)
		second = _generate(ready)["pack"]["cycle_id"]
		self.assertNotEqual(first, second)
		self.assertEqual(
			frappe.db.get_value("Pack", first, ["expiry", "shelf_life_days_applied"]), (first_expiry, 30)
		)
		row = frappe.db.get_value(
			"Pack", second, ["expiry", "shelf_life_days_applied", "packed_at"], as_dict=True
		)
		self.assertEqual(row.shelf_life_days_applied, 20)
		self.assertEqual(getdate(row.expiry), getdate(row.packed_at) + timedelta(days=20))


class TestReprintVoidLookup(IsolatedTestCase):
	def _packed(self, **kwargs):
		ready = make_t4_ready_set(**kwargs)
		return ready, _generate(ready)["pack"]["cycle_id"]

	@bru("BRU-ID-005")
	def test_reprint_window_boundary(self):
		_ready, cycle_id = self._packed()
		self.assertEqual(_block(self, packing.reprint, cycle_id, "  ", STATION).code, "REASON_REQUIRED")
		# cửa sổ đo bằng giờ server từ lúc sinh Cycle ID (Pack.creation); giờ client (packed_at) lệch bao nhiêu
		# cũng không ảnh hưởng
		created = frappe.utils.get_datetime(frappe.db.get_value("Pack", cycle_id, "creation"))
		frappe.db.set_value("Pack", cycle_id, "packed_at", created - timedelta(days=1))

		with patch.object(packing, "now_datetime", return_value=created + timedelta(seconds=600)):
			result = packing.reprint(cycle_id, "Nhãn bị nhòe", STATION)
		self.assertEqual(result["pack"]["cycle_id"], cycle_id)
		self.assertEqual(result["print"]["status"], "Queued")
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 2)
		job = frappe.get_doc("Print Job", result["print"]["print_job"])
		self.assertEqual((job.reprint_reason, job.ref_name), ("Nhãn bị nhòe", cycle_id))
		self.assertEqual(result["print"]["zpl"], job.payload)

		frappe.db.set_value("Pack", cycle_id, "packed_at", created + timedelta(days=1))
		with patch.object(packing, "now_datetime", return_value=created + timedelta(seconds=601)):
			block = _block(self, packing.reprint, cycle_id, "Nhãn bị nhòe", STATION)
		self.assertEqual((block.code, block.http_status), ("REPRINT_WINDOW_EXPIRED", 409))
		self.assertIn(cycle_id, block.reason)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 2)

	def test_reprint_rejects_unknown_void_or_wrong_station(self):
		_ready, cycle_id = self._packed()
		self.assertEqual(_block(self, packing.reprint, cycle_id, "x", "TR-003").code, "STATION_WRONG_STEP")
		unknown = next_free_test_cycle_id()
		self.assertEqual(_block(self, packing.reprint, unknown, "x", STATION).code, "PACK_NOT_FOUND")
		packing.void(cycle_id, "Torn", STATION)
		block = _block(self, packing.reprint, cycle_id, "x", STATION)
		self.assertEqual(block.code, "STATUS_INVALID_FOR_STATION")
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 1)

	def test_reprint_without_printer_waits_with_warning(self):
		# nhãn đầu đã vào hàng in; sau đó trạm không còn máy in đúng loại nhãn → nhãn in lại chờ (Waiting)
		ready, cycle_id = self._packed(method="Plasma")
		frappe.db.set_value("Printer", ready.printer, "is_active", 0)
		result = packing.reprint(cycle_id, "Kẹt giấy", STATION)
		self.assertEqual(result["print"]["status"], "Waiting")
		self.assertEqual(result["print"]["warning"]["code"], "NO_PRINTER_FOR_METHOD")
		job = frappe.get_doc("Print Job", result["print"]["print_job"])
		self.assertEqual((job.status, job.reprint_reason), ("Waiting", "Kẹt giấy"))
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 2)

	@bru("BRU-ID-005")
	def test_reprint_while_label_waiting_returns_the_waiting_job(self):
		# F3: nhãn chưa in (Waiting) thì in lại không tạo job thứ hai, nếu không đổi cuộn sẽ in hai nhãn cùng Cycle ID
		_ready, cycle_id = self._packed(method="Plasma", with_printer=False)
		[waiting] = _jobs_of(cycle_id)
		result = packing.reprint(cycle_id, "Kẹt giấy", STATION)
		self.assertEqual(result["pack"]["cycle_id"], cycle_id)
		printed = result["print"]
		self.assertEqual(
			{key: printed[key] for key in ("print_job", "status", "printer", "zpl")},
			{"print_job": waiting, "status": "Waiting", "printer": None, "zpl": None},
		)
		warning = printed["warning"]
		self.assertEqual(warning["code"], "LABEL_ALREADY_WAITING")
		for key in ("title", "reason", "action"):
			self.assertTrue(warning[key], msg=key)
		self.assertIn(cycle_id, warning["reason"])
		self.assertIn("CN-", warning["action"])
		self.assertEqual(list(_jobs_of(cycle_id)), [waiting])
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 1)
		self.assertIsNone(frappe.db.get_value("Print Job", waiting, "reprint_reason"))

		# nhãn chờ đã in (không còn Waiting) thì in lại như thường
		frappe.db.set_value("Print Job", waiting, "status", "Printed")
		again = packing.reprint(cycle_id, "Kẹt giấy", STATION)["print"]
		self.assertNotEqual(again["print_job"], waiting)
		self.assertEqual(again["warning"]["code"], "NO_PRINTER_FOR_METHOD")
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 2)

	@bru("BRU-ID-005")
	def test_void_then_regenerate(self):
		ready, cycle_id = self._packed()
		result = packing.void(cycle_id, "Label Damaged", STATION, note=" Nhãn rách góc ")
		self.assertEqual(result["status"], "Void")
		pack = frappe.db.get_value(
			"Pack", cycle_id, ["status", "void_reason", "void_note", "docstatus"], as_dict=True
		)
		self.assertEqual(
			pack,
			{"status": "Void", "void_reason": "Label Damaged", "void_note": "Nhãn rách góc", "docstatus": 1},
		)
		registry = frappe.db.get_value(
			"Code Registry", cycle_id, ["status", "disabled_on", "disabled_reason"], as_dict=True
		)
		self.assertEqual(registry.status, "Disabled")
		self.assertIsNotNone(registry.disabled_on)
		self.assertIn("Label Damaged", registry.disabled_reason)
		gate = _gate(ready.set_id, "T4")
		self.assertEqual((gate.result, gate.redo_count, gate.ref_name), ("Fail", 1, cycle_id))
		unit = _unit(ready.set_id)
		self.assertEqual(unit.status, "Reprocess")
		self.assertIsNone(unit.active_cycle_id)

		second = _generate(ready)["pack"]["cycle_id"]
		self.assertNotEqual(second, cycle_id)
		gate = _gate(ready.set_id, "T4")
		self.assertEqual((gate.result, gate.redo_count, gate.ref_name), ("Pass", 1, second))
		unit = _unit(ready.set_id)
		self.assertEqual((unit.status, unit.active_cycle_id), ("Processing", second))

	@bru("BRU-ID-005")
	def test_void_cancels_waiting_labels_but_not_queued_ones(self):
		# chưa có máy in đúng loại nhãn: nhãn của gói chờ (Waiting); hủy gói thì nhãn chờ không bao giờ được in
		ready, first = self._packed(method="Plasma", with_printer=False)
		steam_label, plasma_label = make_label_items()
		printer = make_printer(STATION, steam_label)
		[(old_job, (status, _error))] = _jobs_of(first).items()
		self.assertEqual(status, "Waiting")

		packing.void(first, "Label Damaged", STATION)
		status, error = _jobs_of(first)[old_job]
		self.assertEqual(status, "Failed")
		self.assertIn(first, error)
		self.assertIn("Label Damaged", error)

		second = _generate(ready)["pack"]["cycle_id"]
		[new_job] = _jobs_of(second)
		released = core_print.set_roll(printer, make_roll(plasma_label))["released_jobs"]
		self.assertEqual([job["print_job"] for job in released], [new_job])
		self.assertEqual(_jobs_of(first)[old_job][0], "Failed")
		self.assertEqual(_jobs_of(second)[new_job][0], "Queued")

		# nhãn đã vào hàng in (Queued) giữ nguyên khi hủy: agent có thể đang in
		packing.void(second, "Torn", STATION)
		self.assertEqual(_jobs_of(second)[new_job], ("Queued", None))

	def test_void_only_packed(self):
		ready, cycle_id = self._packed()
		for reason in ("", None, "Dropped"):
			block = _block(self, packing.void, cycle_id, reason, STATION)
			self.assertEqual((block.code, block.http_status), ("REASON_REQUIRED", 422), msg=reason)
		self.assertEqual(
			_block(self, packing.void, next_free_test_cycle_id(), "Torn", STATION).code, "PACK_NOT_FOUND"
		)
		self.assertEqual(_block(self, packing.void, cycle_id, "Torn", "TR-005").code, "STATION_WRONG_STEP")
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "Packed")

		packing.void(cycle_id, "Torn", STATION)
		block = _block(self, packing.void, cycle_id, "Torn", STATION)
		self.assertEqual((block.code, block.http_status), ("PACK_NOT_VOIDABLE", 409))
		self.assertEqual(_gate(ready.set_id, "T4").redo_count, 1)

		_ready2, loaded = self._packed()
		frappe.db.set_value("Pack", loaded, "status", "In Load")
		self.assertEqual(_block(self, packing.void, loaded, "Torn", STATION).code, "PACK_NOT_VOIDABLE")

	def test_lookup_returns_pack_details(self):
		_ready, cycle_id = self._packed()
		pack = frappe.get_doc("Pack", cycle_id)
		packed_at = frappe.utils.get_datetime(pack.packed_at)
		hri = gs1.cycle_hri(pack.gtin, packed_at.date(), getdate(pack.expiry), cycle_id)
		expected = {
			"cycle_id": cycle_id,
			"set_id": pack.set_unit,
			"set_name": pack.set_name,
			"packed_at": f"{packed_at:%Y-%m-%d %H:%M:%S}",
			"packer": get_fullname(pack.packed_by_user),
			"expiry": str(getdate(pack.expiry)),
			"method": "Steam",
			"pack_type": pack.pack_type,
			"ci_batch": pack.ci_batch,
			"status": "Packed",
			"label_print_count": 1,
		}
		self.assertEqual(packing.lookup(hri), expected)
		self.assertEqual(packing.lookup(cycle_id), expected)
		self.assertEqual(packing.lookup(f" ]d2{pack.barcode_payload}\r\n"), expected)

	def test_lookup_unknown(self):
		self.assertEqual(_block(self, packing.lookup, "abc").code, "SCAN_INVALID")
		ready = make_t4_ready_set()
		self.assertEqual(_block(self, packing.lookup, ready.set_id).code, "SCAN_INVALID")
		block = _block(self, packing.lookup, next_free_test_cycle_id())
		self.assertEqual((block.code, block.http_status), ("PACK_NOT_FOUND", 404))


class TestLabelContext(IsolatedTestCase):
	def test_label_context_has_template_keys_and_display_formats(self):
		ready = make_t4_ready_set(set_type_name="Bộ phẫu thuật", is_loaner=1)
		client_ts = parse_client_ts("2026-10-21T00:30:00+07:00")
		with patch.object(client_time, "utc_now", return_value=client_ts):
			result = _generate(ready, client_ts=client_ts)
		pack = frappe.get_doc("Pack", result["pack"]["cycle_id"])
		context = pack_label.label_context(pack)
		self.assertEqual(set(context), set(sample_pack_context()))
		self.assertEqual(
			{key: context[key] for key in ("set_id", "cycle_id", "set_name", "packed_at", "expiry", "dept")},
			{
				"set_id": ready.set_id,
				"cycle_id": pack.name,
				"set_name": "Bộ phẫu thuật",
				"packed_at": "21/10/2026 00:30",
				"expiry": "20/11/2026",
				"dept": "",
			},
		)
		self.assertEqual(context["packer"], get_fullname(pack.packed_by_user))
		self.assertEqual(context["pack_type"], frappe.db.get_value("Item", pack.pack_type, "item_name"))
		self.assertEqual(context["ci_lot"], pack.ci_batch)
		self.assertEqual(context["bom_version"], 1)
		self.assertIs(context["is_loaner"], True)
		self.assertIs(context["is_test"], True)
		self.assertEqual(context["payload"], pack.barcode_payload)
		self.assertEqual(context["hri"], result["hri"])
		self.assertEqual(context["warning"], "")
		self.assertTrue(result["pack"]["is_loaner"])


class TestPackerName(IsolatedTestCase):
	"""Tên trên nhãn và tóm tắt: nhân viên của phiên; gói cũ chưa có `packed_by` lấy theo user (#1841, A-81)."""

	def test_employee_name_wins_and_old_packs_fall_back_to_the_user(self):
		employee = make_employee(first_name="Nhân Viên Thẻ")
		pack = frappe._dict(packed_by=employee.name, packed_by_user="Administrator")
		self.assertEqual(pack_label.packer_name(pack), employee.employee_name)
		old = frappe._dict(packed_by=None, packed_by_user="Administrator")
		self.assertEqual(pack_label.packer_name(old), get_fullname("Administrator"))
		gone = frappe._dict(packed_by="HR-EMP-KHONG-CO", packed_by_user="Administrator")
		self.assertEqual(pack_label.packer_name(gone), get_fullname("Administrator"))
