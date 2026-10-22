"""Cấp Set ID hàng loạt (FEAT-016 Task 2; FR-M1-05, .1, .2; BRU-ID-001, BRU-ID-006; UC-03 A1, E3; G1, G4-G6)."""

import inspect
import threading
from unittest.mock import patch

import frappe
import frappe.client
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from tracecore.core import code_registry, gs1
from tracecore.core.errors import BlockedError
from tracecore.core.tests.test_code_registry import production_site
from tracecore.instrument import catalog, set_units
from tracecore.setup import devdata
from tracecore.tests import factories
from tracecore.tests.factories import (
	make_bom,
	make_department,
	make_instrument,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import bru

# Set Unit liên kết Department, Zone Station, Instrument Set Type (→ Item) và User (tag_verified_by); CI chưa có
# Setup Wizard nên không để test runner tự tạo test record ERPNext/HRMS
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SET_TYPE = "Instrument Set Type"


def _series_key(type_code):
	return f"{code_registry.company_prefix()}{type_code}"


def _series(type_code):
	row = frappe.db.sql("select `current` from `tabSeries` where name = %s", _series_key(type_code))
	return row[0][0] if row else None


def _blocked(test, fn, *args, **kwargs):
	with test.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


DERIVED_MAX = 500  # cơ số của dụng cụ mặc định: cơ số bộ suy ra khi không nhập


def _set_type(code, lines=None, **kwargs):
	"""Loại bộ có BOM v1 hiệu lực hôm nay (mặc định một dụng cụ riêng của loại bộ, cơ số ``DERIVED_MAX``)."""
	if not lines:
		make_instrument(f"SU-{code}", max_cycles=DERIVED_MAX, methods=factories.BOM_INSTRUMENT_METHODS)
	return make_set_type(code, bom=lines or [(f"SU-{code}", 1)], **kwargs).name


def _footprint(type_code):
	"""Đếm những gì một lần cấp để lại: Set Unit, sổ mã, Audit, bộ đếm series."""
	return {
		"units": frappe.db.count("Set Unit", {"set_type": type_code}),
		"codes": frappe.db.count("Code Registry"),
		"audit": frappe.db.count("Audit Log"),
		"series": _series(type_code),
	}


class TestIssueBatch(FrappeTestCase):
	@bru("BRU-ID-006")
	def test_issue_batch_creates_new_units_registered(self):
		set_type = _set_type("SUA")
		department = frappe.db.get_value(SET_TYPE, set_type, "department")
		names = set_units.issue_batch(set_type, 5, max_cycles=250)
		self.assertEqual(len(names), 5)
		serials = [int(name[-6:]) for name in names]
		self.assertEqual(serials, list(range(serials[0], serials[0] + 5)))
		for name in names:
			row = frappe.db.get_value(
				"Set Unit",
				name,
				[
					"set_id",
					"set_type",
					"department",
					"max_cycles",
					"status",
					"cycles_used",
					"current_cycle_no",
					"cycle_bom_version",
					"active_cycle_id",
					"current_station",
					"cycles_source",
				],
				as_dict=True,
			)
			self.assertEqual(
				row,
				{
					"set_id": name,
					"set_type": set_type,
					"department": department,
					"max_cycles": 250,
					"status": "New",
					"cycles_used": 0,
					"current_cycle_no": 0,
					"cycle_bom_version": 0,
					"active_cycle_id": None,
					"current_station": None,
					"cycles_source": "Actual",
				},
			)
			self.assertEqual(
				frappe.db.get_value("Code Registry", name, ["prefix", "ref_doctype", "ref_name"]),
				(_series_key(set_type), "Set Unit", name),
			)
			created = frappe.get_all(
				"Audit Log",
				filters={"ref_doctype": "Set Unit", "ref_name": name, "action": "Create"},
				pluck="reason",
			)
			self.assertEqual(created, ["issue"])
		batch = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": SET_TYPE, "ref_name": set_type, "action": "Create", "reason": "issue"},
			fields=["new_value"],
		)
		self.assertEqual(len(batch), 1)
		self.assertEqual(
			frappe.parse_json(batch[0].new_value),
			{"count": 5, "first": names[0], "last": names[-1], "department": department, "origin": "New"},
		)

	def test_issue_batch_count_limits(self):
		set_type = _set_type("SUC")
		self.assertEqual(set_units.MAX_BATCH, 100)
		before = _footprint(set_type)
		for value in (0, -1, 101, "2.5", True, False, "1e2", 10**9, None, 2.0, "", " ", [3]):
			with self.subTest(value=value):
				block = _blocked(self, set_units.issue_batch, set_type, value)
				self.assertEqual((block.code, block.http_status), ("COUNT_OUT_OF_RANGE", 422))
				self.assertIn("100", block.reason)
		self.assertEqual(_footprint(set_type), before)
		self.assertEqual(set_units.parse_count(" 7 "), 7)
		self.assertEqual(len(set_units.issue_batch(set_type, 1)), 1)
		self.assertEqual(len(set_units.issue_batch(set_type, "100")), 100)
		self.assertEqual(frappe.db.count("Set Unit", {"set_type": set_type}), 101)

	@bru("BRU-ID-001")
	def test_batch_of_100_unique_and_contiguous(self):
		set_type = _set_type("SUH")
		names = set_units.issue_batch(set_type, 100)
		self.assertEqual(len(set(names)), 100)
		serials = [int(name[-6:]) for name in names]
		self.assertEqual(serials, list(range(serials[0], serials[0] + 100)))
		for name in names:
			self.assertEqual(gs1.split_set_id(name, set_type), (code_registry.company_prefix(), name[-6:]))
			for raw in (name, gs1.giai_payload(name), gs1.giai_hri(name)):
				result = gs1.parse_scan(raw)
				self.assertEqual((result["type"], result["id"]), ("set", name))

	@bru("BRU-ID-001")
	def test_failure_mid_batch_rolls_back_everything(self):
		set_type = _set_type("SUF")
		set_units.issue_batch(set_type, 1)  # series đã có
		before = _footprint(set_type)
		real_register = code_registry.register
		calls = []

		def failing(*args, **kwargs):
			calls.append(args[0])
			if len(calls) == 37:
				raise RuntimeError("disk full")
			return real_register(*args, **kwargs)

		with patch.object(code_registry, "register", side_effect=failing):
			with self.assertRaises(RuntimeError):
				set_units.issue_batch(set_type, 100)
		self.assertEqual(len(calls), 37)
		self.assertEqual(_footprint(set_type), before)
		for code in calls:
			self.assertFalse(code_registry.is_issued(code))
			self.assertFalse(frappe.db.exists("Set Unit", code))
		# không thủng số: lô kế tiếp bắt đầu đúng số đáng lẽ của bộ thứ nhất
		self.assertEqual(set_units.issue_batch(set_type, 2)[0], calls[0])

	def test_series_exhausted_is_block_and_rolls_back(self):
		# carry-over review Task 1: hết dải giữa lô → Block có mã (RPC chỉ đổi BlockedError), không đốt số
		set_type = _set_type("SUX")
		frappe.db.sql(
			"insert into `tabSeries` (`name`, `current`) values (%s, %s) on duplicate key update `current` = %s",
			(_series_key(set_type), 999998, 999998),
		)
		before = _footprint(set_type)
		block = _blocked(self, set_units.issue_batch, set_type, 3)
		self.assertEqual((block.code, block.http_status), ("SET_SERIES_EXHAUSTED", 409))
		self.assertIn(set_type, block.reason)
		self.assertEqual(_footprint(set_type), before)
		self.assertEqual(_series(set_type), 999998)
		self.assertEqual(set_units.issue_batch(set_type, 1), [f"{_series_key(set_type)}999999"])

	def test_precheck_set_type_bom_rules(self):
		block = _blocked(self, set_units.precheck, "NOPE404")
		self.assertEqual((block.code, block.http_status), ("SET_TYPE_NOT_FOUND", 404))
		for value in (None, "", 5, ["SUA"]):
			self.assertEqual(_blocked(self, set_units.precheck, value).code, "SET_TYPE_NOT_FOUND")

		bare = make_set_type("SUB0").name
		block = _blocked(self, set_units.precheck, bare)
		self.assertEqual((block.code, block.http_status), ("SET_TYPE_BOM_INVALID", 422))
		self.assertEqual([item["code"] for item in block.items], ["NO_EFFECTIVE_BOM"])

		scheduled = make_set_type("SUB1").name
		make_bom(scheduled, [("SU-B1", 1)], effective_from=add_days(now_datetime(), 1))
		block = _blocked(self, set_units.precheck, scheduled)
		self.assertEqual([item["code"] for item in block.items], ["NO_EFFECTIVE_BOM"])

		retired = _set_type("SUB2", [("SU-R1", 1), ("SU-R2", 1)])
		catalog.retire("SU-R2", "Broken", confirm=True)
		block = _blocked(self, set_units.precheck, retired)
		self.assertEqual(block.code, "SET_TYPE_BOM_INVALID")
		self.assertEqual(
			[(item["row"], item["instrument"], item["code"]) for item in block.items],
			[(2, "SU-R2", "RETIRED")],
		)
		self.assertIn("SU-R2", block.items[0]["message"])

		incompatible = make_set_type("SUB3").name
		make_instrument("SU-P1", methods=("Plasma",))
		make_bom(incompatible, [("SU-B3", 1), ("SU-P1", 1)], legacy=True)
		block = _blocked(self, set_units.precheck, incompatible)
		self.assertEqual(
			[(item["row"], item["instrument"], item["code"]) for item in block.items],
			[(2, "SU-P1", "INCOMPATIBLE")],
		)

		valid = _set_type("SUB4")
		make_bom(valid, [("SU-B4", 2)], version=2, effective_from=add_days(now_datetime(), 3))
		before = frappe.db.count("Audit Log"), frappe.db.count("Code Registry"), _series(valid)
		with self.assertQueryCount(10):  # số truy vấn cố định, một truy vấn cho dụng cụ của BOM
			ctx = set_units.precheck(valid, max_cycles=300)
		self.assertEqual(
			(frappe.db.count("Audit Log"), frappe.db.count("Code Registry"), _series(valid)), before
		)
		self.assertEqual(ctx["bom_version"], 1)
		self.assertEqual(
			{k: ctx[k] for k in ("set_type", "type_code", "max_cycles", "origin", "cycles_used", "warnings")},
			{
				"set_type": valid,
				"type_code": valid,
				"max_cycles": 300,
				"origin": "New",
				"cycles_used": 0,
				"warnings": [],
			},
		)

	def test_precheck_department_and_max_cycles(self):
		make_instrument("SU-MC1", max_cycles=200, methods=factories.BOM_INSTRUMENT_METHODS)
		set_type = _set_type("SUD", [("SU-MC1", 1)])
		own = frappe.db.get_value(SET_TYPE, set_type, "department")
		ctx = set_units.precheck(set_type, max_cycles=150)
		self.assertEqual((ctx["department"], ctx["derived_max_cycles"], ctx["warnings"]), (own, 200, []))
		other = make_department("SU other department")
		self.assertEqual(set_units.precheck(set_type, other, 150)["department"], other)

		group = make_department("SU group department")
		frappe.db.set_value("Department", group, "is_group", 1)
		disabled = make_department("SU disabled department")
		frappe.db.set_value("Department", disabled, "disabled", 1)
		for value in (group, disabled, "SU no such department", 7):
			with self.subTest(department=value):
				block = _blocked(self, set_units.precheck, set_type, value, 150)
				self.assertEqual((block.code, block.http_status), ("DEPARTMENT_INVALID", 422))
		no_department = _set_type("SUD2")
		frappe.db.set_value(SET_TYPE, no_department, "department", None)
		self.assertEqual(
			_blocked(self, set_units.precheck, no_department, None, 150).code, "DEPARTMENT_INVALID"
		)

		for value in (0, -5, 100000, "abc", "2.5", True, 1.5, [1]):
			with self.subTest(max_cycles=value):
				block = _blocked(self, set_units.precheck, set_type, None, value)
				self.assertEqual((block.code, block.http_status), ("MAX_CYCLES_INVALID", 422))
		self.assertEqual(
			set_units.precheck(set_type, None, "99999")["max_cycles"], set_units.MAX_CYCLES_LIMIT
		)
		# không nhập: lấy cơ số suy ra; không suy ra được → bắt buộc nhập
		self.assertEqual(set_units.precheck(set_type)["max_cycles"], 200)
		undefined = make_set_type("SUD3", bom=[("SU-UNDEF", 1)]).name  # dụng cụ cơ số Chưa xác định
		self.assertIsNone(set_units.precheck(undefined, max_cycles=10)["derived_max_cycles"])
		self.assertEqual(_blocked(self, set_units.precheck, undefined).code, "MAX_CYCLES_INVALID")

		# lớn hơn cơ số suy ra: cảnh báo, vẫn cấp
		ctx = set_units.precheck(set_type, max_cycles=300)
		self.assertEqual([w["code"] for w in ctx["warnings"]], ["MAX_CYCLES_ABOVE_DERIVED"])
		names = set_units.issue_batch(set_type, 2, max_cycles=300)
		self.assertEqual(frappe.db.get_value("Set Unit", names[0], "max_cycles"), 300)

	def test_existing_sets_estimated_cycles(self):
		set_type = _set_type("SUE")
		names = set_units.issue_batch(set_type, 3, max_cycles=300, origin="Existing", cycles_used=120)
		for name in names:
			self.assertEqual(
				frappe.db.get_value("Set Unit", name, ["status", "cycles_used", "cycles_source"]),
				("New", 120, "Estimated"),
			)
		batch = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": SET_TYPE, "ref_name": set_type, "action": "Create", "reason": "issue"},
			pluck="new_value",
		)
		self.assertEqual(frappe.parse_json(batch[0])["origin"], "Existing")
		self.assertEqual(
			set_units.precheck(set_type, None, 300, "Existing", "0")["cycles_used"], 0
		)  # bộ cũ chưa dùng lần nào
		before = _footprint(set_type)
		for cycles_used in (300, 301, -1, "abc", 2.5, None):
			with self.subTest(cycles_used=cycles_used):
				block = _blocked(
					self,
					set_units.issue_batch,
					set_type,
					2,
					max_cycles=300,
					origin="Existing",
					cycles_used=cycles_used,
				)
				self.assertEqual(block.code, "MAX_CYCLES_INVALID")
		# bộ mới luôn 0 chu trình
		self.assertEqual(
			_blocked(self, set_units.issue_batch, set_type, 1, max_cycles=300, cycles_used=5).code,
			"MAX_CYCLES_INVALID",
		)
		with self.assertRaises(frappe.ValidationError):
			set_units.precheck(set_type, None, 300, "Loaner")
		self.assertEqual(_footprint(set_type), before)

	def test_demo_prefix_blocks_issue_outside_dev_test(self):
		set_type = _set_type("SUG")
		bare = make_set_type("SUG0").name
		before = _footprint(set_type)
		conf, flags = production_site(tc_gs1_company_prefix="9520000")
		with conf, flags:
			self.assertEqual(_blocked(self, set_units.precheck, "NOPE404").code, "SET_TYPE_NOT_FOUND")
			block = _blocked(self, set_units.issue_batch, set_type, 2)
			self.assertEqual((block.code, block.http_status), ("GS1_PREFIX_NOT_CONFIGURED", 409))
			# tiền tố trước khoa/cơ số/BOM
			self.assertEqual(
				_blocked(self, set_units.precheck, bare, "x", 0).code, "GS1_PREFIX_NOT_CONFIGURED"
			)
		self.assertEqual(_footprint(set_type), before)


class TestSetUnitCreationGuard(FrappeTestCase):
	@bru("BRU-ID-001")
	def test_direct_insert_blocked(self):
		set_type = _set_type("SUI")
		set_units.issue_batch(set_type, 1)
		before = _footprint(set_type)
		values = {"doctype": "Set Unit", "set_type": set_type, "max_cycles": 100}
		with self.assertRaises(frappe.ValidationError) as raised:
			frappe.get_doc(dict(values)).insert(ignore_permissions=True)
		self.assertIn("Set ID", str(raised.exception))
		frappe.flags.in_import = True
		try:
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc(dict(values)).insert()
		finally:
			frappe.flags.in_import = False
		with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
			frappe.client.insert(dict(values))
		self.assertEqual(_footprint(set_type), before)  # chặn trước khi cấp mã: không đốt số

		manager = make_user("su-system-manager@example.com", ["System Manager"])
		self.assertFalse(frappe.has_permission("Set Unit", "create", user=manager))
		self.assertTrue(frappe.has_permission("Set Unit", "read", user=manager))
		self.assertTrue(frappe.has_permission("Set Unit", "write", user=manager))
		for role in [f"TC R{n:02d}" for n in range(1, 11)]:
			perms = [p for p in frappe.get_meta("Set Unit").permissions if p.role == role]
			self.assertEqual([(p.read, p.write, p.create) for p in perms], [(1, 0, 0)], msg=role)

	@bru("BRU-ID-001")
	def test_set_id_and_new_fields_not_editable(self):
		unit = make_set_unit(_set_type("SUJ"))
		for field, value in (
			("set_id", code_registry.company_prefix() + "SUJ999999"),
			("cycles_source", "Estimated"),
			("tag_verified_on", now_datetime()),
			("tag_verified_by", "Administrator"),
			("status", "Sterile"),
			("cycles_used", 3),
			("cycle_bom_version", 2),
		):
			doc = frappe.get_doc("Set Unit", unit.name)
			doc.set(field, value)
			with self.assertRaises(frappe.ValidationError, msg=field):
				doc.save()
		row = frappe.db.get_value(
			"Set Unit", unit.name, ["cycles_source", "tag_verified_on", "tag_verified_by"], as_dict=True
		)
		self.assertEqual(row, {"cycles_source": "Actual", "tag_verified_on": None, "tag_verified_by": None})
		meta = frappe.get_meta("Set Unit")
		self.assertTrue(meta.get_field("cycles_source").read_only)
		self.assertTrue(meta.get_field("cycles_source").set_only_once)
		self.assertEqual(meta.get_field("cycles_source").options.split("\n"), ["Actual", "Estimated"])
		self.assertTrue(meta.get_field("tag_verified_on").read_only)
		self.assertEqual(meta.get_field("tag_verified_by").options, "User")

	def test_factory_and_devdata_use_issue_path(self):
		unit = make_set_unit(_set_type("SUK"), max_cycles=120, is_loaner=1)
		self.assertEqual(
			(unit.status, unit.max_cycles, unit.is_loaner, unit.cycles_source), ("New", 120, 1, "Actual")
		)
		self.assertEqual(
			frappe.get_all(
				"Audit Log",
				filters={"ref_doctype": "Set Unit", "ref_name": unit.name, "action": "Create"},
				pluck="reason",
			),
			["issue"],
		)
		for module in (factories, devdata):
			source = inspect.getsource(module)
			self.assertNotRegex(source, r"[\"']doctype[\"']:\s*[\"']Set Unit[\"']", msg=module.__name__)
		set_id = devdata.ensure_demo_set()
		self.assertEqual(frappe.db.get_value("Set Unit", set_id, "status"), "New")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": "Set Unit", "ref_name": set_id, "action": "Create", "reason": "issue"},
			)
		)

	def test_patch_backfills_cycles_source(self):
		from tracecore.patches.v0_1 import set_unit_issue_fields

		set_type = _set_type("SUL")
		old = make_set_unit(set_type).name
		estimated = set_units.issue_batch(set_type, 1, max_cycles=300, origin="Existing", cycles_used=4)[0]
		frappe.db.sql("update `tabSet Unit` set cycles_source = null where name = %s", old)
		audit = frappe.db.count("Audit Log")
		set_unit_issue_fields.execute()
		set_unit_issue_fields.execute()
		self.assertEqual(frappe.db.get_value("Set Unit", old, "cycles_source"), "Actual")
		self.assertEqual(frappe.db.get_value("Set Unit", estimated, "cycles_source"), "Estimated")
		self.assertIsNone(frappe.db.get_value("Set Unit", old, "department"))  # không bịa khoa
		self.assertEqual(frappe.db.count("Audit Log"), audit)
		with open(frappe.get_app_path("tracecore", "patches.txt"), encoding="utf-8") as handle:
			post = handle.read().split("[post_model_sync]", 1)[1]
		self.assertIn("tracecore.patches.v0_1.set_unit_issue_fields", post)


class TestConcurrentIssue(FrappeTestCase):
	"""Hai kết nối DB thật cùng cấp lô cho một loại bộ (Review Focus 1, G1)."""

	CODE = "SUCC"
	INSTRUMENT = "SU-CC1"

	def _cleanup(self):
		# dữ liệu đã commit (hai kết nối thật): xóa thẳng DB, kể cả Audit Log (append-only chỉ chặn ở
		# Document/permission; đây là dọn dữ liệu test)
		frappe.db.rollback()
		units = frappe.get_all("Set Unit", filters={"set_type": self.CODE}, pluck="name")
		lines = frappe.get_all("Set BOM Item", filters={"set_type": self.CODE}, pluck="name")
		for doctype, names in (("Set Unit", units), ("Set BOM Item", lines)):
			if names:
				frappe.db.delete("Audit Log", {"ref_doctype": doctype, "ref_name": ["in", names]})
		if units:
			frappe.db.delete("Audit Log", {"ref_doctype": "Code Registry", "ref_name": ["in", units]})
		frappe.db.delete("Set Unit", {"set_type": self.CODE})
		frappe.db.delete("Code Registry", {"prefix": _series_key(self.CODE)})
		frappe.db.delete("Set BOM Item", {"set_type": self.CODE})
		frappe.db.delete("Comment", {"reference_doctype": SET_TYPE, "reference_name": self.CODE})
		frappe.db.delete("Audit Log", {"ref_doctype": SET_TYPE, "ref_name": self.CODE})
		frappe.db.delete(SET_TYPE, {"name": self.CODE})
		frappe.db.delete("Instrument Compatible Method", {"parent": self.INSTRUMENT})
		frappe.db.delete("Audit Log", {"ref_doctype": "Instrument", "ref_name": self.INSTRUMENT})
		frappe.db.delete("Instrument", {"name": self.INSTRUMENT})
		frappe.db.sql("delete from `tabSeries` where name = %s", _series_key(self.CODE))
		frappe.db.commit()

	def test_concurrent_batches_same_type_never_duplicate(self):
		self._cleanup()
		# loại bộ mới, CHƯA có dòng tabSeries: hai lô đầu tiên cùng lúc không được deadlock/trùng
		make_set_type(self.CODE, bom=[(self.INSTRUMENT, 1)])
		frappe.db.commit()
		self.addCleanup(self._cleanup)
		site, sites_path = frappe.local.site, frappe.local.sites_path
		results, errors = {}, []
		a_issued = threading.Event()  # A đã cấp xong lô (giữ khóa series), chưa commit
		release_a = threading.Event()
		b_started = threading.Event()
		b_done = threading.Event()

		def request(key, before_commit=None, started=None, done=None):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				if started:
					started.set()
				results[key] = set_units.issue_batch(self.CODE, 20, max_cycles=300)
				if before_commit:
					before_commit()
				frappe.db.commit()
			except Exception as error:  # pragma: no cover - chỉ để báo lỗi của luồng phụ
				errors.append((key, error))
				frappe.db.rollback()
			finally:
				a_issued.set()
				if done:
					done.set()
				frappe.destroy()

		def hold():
			a_issued.set()
			release_a.wait(timeout=60)

		first = threading.Thread(target=request, args=("a", hold))
		second = threading.Thread(target=request, args=("b", None, b_started, b_done))
		first.start()
		try:
			self.assertTrue(a_issued.wait(timeout=60))
			second.start()
			self.assertTrue(b_started.wait(timeout=60))
			# B không thể xong khi A còn giữ khóa dòng series tới commit
			self.assertFalse(b_done.wait(timeout=1))
		finally:
			release_a.set()
			first.join(timeout=120)
			if second.is_alive() or second.ident:
				second.join(timeout=120)
		self.assertEqual(errors, [])
		a, b = results["a"], results["b"]
		self.assertEqual(len(set(a + b)), 40)
		for batch in (a, b):
			serials = [int(name[-6:]) for name in batch]
			self.assertEqual(serials, list(range(serials[0], serials[0] + 20)))
		self.assertEqual(int(b[0][-6:]), int(a[-1][-6:]) + 1)
		frappe.db.rollback()
		self.assertEqual(frappe.db.count("Set Unit", {"set_type": self.CODE}), 40)
		self.assertEqual(frappe.db.count("Code Registry", {"prefix": _series_key(self.CODE)}), 40)
