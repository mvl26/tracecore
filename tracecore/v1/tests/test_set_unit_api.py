import base64
import csv
import io
import time
import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry, gs1, step_gate
from tracecore.core import print as core_print
from tracecore.core.tests.test_code_registry import production_site
from tracecore.instrument import set_tags, set_units
from tracecore.tests.factories import (
	BOM_INSTRUMENT_METHODS,
	deactivate_printers,
	make_department,
	make_instrument,
	make_label_items,
	make_printer,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, allow_local_printers, bru, request_headers
from tracecore.v1 import set_unit as api
from tracecore.v1._common import BadRequestError

# Set Unit -> Department, Zone Station, Instrument Set Type (-> Item), User; Print Job -> Printer -> Item, User
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

TS = "2026-10-19T09:00:00+07:00"


def scan(raw, key=None):
	headers = {"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": "TR-004"}
	with request_headers(headers):
		return api.get(set_id=raw, client_ts=TS)


class TestSetUnitApi(FrappeTestCase):
	def test_get_returns_set_unit_under_1s(self):
		su = make_set_unit(set_type=make_set_type("API", set_type_name="API set").name, max_cycles=300)
		started = time.perf_counter()
		result = scan("]d2\x1d8004" + su.name + "\r\n")
		elapsed = time.perf_counter() - started
		self.assertTrue(result["ok"])
		data = result["set_unit"]
		self.assertEqual(data["set_id"], su.name)
		self.assertEqual(data["set_type"], "API")
		self.assertEqual(data["set_type_name"], "API set")
		self.assertEqual(data["method"], "Steam")
		self.assertEqual(data["status"], "New")
		self.assertEqual((data["cycles_used"], data["max_cycles"]), (0, 300))
		self.assertLess(elapsed, 1.0)

	@bru("BRU-ID-006")
	def test_get_unknown_code_vietnamese_error_and_audit(self):
		frappe.local.lang = "vi"
		try:
			result = scan("XYZ-123")
		finally:
			frappe.local.lang = "en"
		self.assertFalse(result["ok"])
		error = result["error"]
		self.assertEqual(error["code"], "SCAN_INVALID")
		self.assertEqual(error["title"], "Mã không hợp lệ")
		self.assertIn("XYZ-123", error["reason"])
		self.assertTrue(error["action"])
		log = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject", "reason": "SCAN_INVALID"},
			fields=["station", "new_value"],
			# Audit Log đặt tên autoincrement: dòng chèn sau cùng (timestamp có thể lùi khi đồng hồ WSL nhảy)
			order_by="name desc",
			limit=1,
		)[0]
		self.assertEqual(log.station, "TR-004")
		self.assertEqual(frappe.parse_json(log.new_value)["raw"], "XYZ-123")

	def test_get_without_read_permission_writes_nothing(self):
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		frappe.set_user(make_user("api-nobody@example.com"))
		try:
			with self.assertRaises(frappe.PermissionError):
				scan("XYZ-123")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before)

	def test_get_long_garbage_is_truncated(self):
		result = scan("X" * 5000)
		self.assertEqual(result["error"]["code"], "SCAN_INVALID")
		self.assertLess(len(result["error"]["reason"]), 300)
		log = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject", "reason": "SCAN_INVALID"},
			fields=["new_value"],
			# Audit Log đặt tên autoincrement: dòng chèn sau cùng (timestamp có thể lùi khi đồng hồ WSL nhảy)
			order_by="name desc",
			limit=1,
		)[0]
		self.assertLessEqual(len(frappe.parse_json(log.new_value)["raw"]), 120)

	def test_get_wrong_type(self):
		result = scan("TR-004")
		self.assertEqual(result["error"]["code"], "SCAN_WRONG_TYPE")

	def test_get_not_found(self):
		result = scan(code_registry.company_prefix() + "NOPE000001")
		self.assertEqual(result["error"]["code"], "SET_NOT_FOUND")

	def test_get_requires_read_permission(self):
		su = make_set_unit()
		frappe.set_user(make_user("api-noperm@example.com"))
		try:
			with self.assertRaises(frappe.PermissionError):
				scan(su.name)
		finally:
			frappe.set_user("Administrator")

	def test_get_allowed_for_station_role(self):
		su = make_set_unit()
		frappe.set_user(make_user("api-r04@example.com", roles=["TC R04"]))
		try:
			self.assertTrue(scan(su.name)["ok"])
		finally:
			frappe.set_user("Administrator")

	def test_get_replay_same_key(self):
		su = make_set_unit()
		key = str(uuid.uuid4())
		self.assertEqual(scan(su.name, key), scan(su.name, key))


# ---------------------------------------------------------------------------------------------------------------------
# FEAT-016 Task 5: cấp lô, in, in lại, hủy lệnh in kẹt, xem trước, trạng thái in, quét kiểm tra, CSV khắc
# (FR-M1-05, .1, .3, .4; BRU-ID-001, BRU-ID-006; UC-03 A1, A2, E1-E3; A-09 G1, G3, G7, G9, G10, G12, G16)
# ---------------------------------------------------------------------------------------------------------------------

STATION = "TR-004"
REAL_PREFIX = "8931234"


class _Request:
	def __init__(self, method, headers):
		self.method = method
		self.headers = headers


def _call(method, fn, key=None, **kwargs):
	"""Gọi RPC như một request `method` (POST mang X-Idempotency-Key); trả ``(kết quả, frappe.local.response)``.

	``response["_commit"]`` = `frappe.local.flags.commit` sau lời gọi (request GET chỉ commit khi cờ này bật).
	"""
	previous = getattr(frappe.local, "request", None)
	saved_response, saved_commit = frappe.local.response, frappe.local.flags.commit
	headers = {"X-Idempotency-Key": key or str(uuid.uuid4())} if method == "POST" else {}
	frappe.local.request = _Request(method, headers)
	frappe.local.response = response = frappe._dict()
	frappe.local.flags.commit = False
	try:
		result = fn(**kwargs)
	finally:
		response["_commit"] = frappe.local.flags.commit
		frappe.local.response, frappe.local.flags.commit = saved_response, saved_commit
		if previous is None:
			del frappe.local.request
		else:
			frappe.local.request = previous
	return result, response


def post(fn, key=None, **kwargs):
	return _call("POST", fn, key, **kwargs)


def get(fn, **kwargs):
	return _call("GET", fn, **kwargs)


def last_reject():
	return frappe.get_all(
		"Audit Log",
		filters={"action": "Reject"},
		fields=["reason", "ref_doctype", "ref_name", "new_value"],
		order_by="name desc",
		limit=1,
	)[0]


class SetUnitRpcCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.label_item = make_label_items()[0]
		allow_local_printers(self)
		enqueue = patch.object(frappe, "enqueue")
		self.enqueue = enqueue.start()
		self.addCleanup(enqueue.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		self.set_type = self.make_type("TFIVE")
		self.printer = self.make_printer()
		self.r02 = make_user("t5-r02@example.com", ["TC R02"])
		self.r10 = make_user("t5-r10@example.com", ["TC R10"])
		self.r04 = make_user("t5-r04@example.com", ["TC R04"])
		self.r01 = make_user("t5-r01@example.com", ["TC R01"])

	def make_type(self, code, **kwargs):
		make_instrument(f"SU-{code}", max_cycles=500, methods=BOM_INSTRUMENT_METHODS)
		return make_set_type(code, bom=[(f"SU-{code}", 1)], **kwargs).name

	def make_printer(self, host="127.0.0.1"):
		user = frappe.session.user
		frappe.set_user("Administrator")  # máy in do R10/System Manager cấu hình, không phải người gọi RPC
		try:
			return make_printer(STATION, self.label_item, host=host)
		finally:
			frappe.set_user(user)

	def dispatch_calls(self):
		return [
			c
			for c in self.enqueue.call_args_list
			if c.args[:1] == ("tracecore.core.print_server.dispatch_many",)
		]

	def units(self, count, set_type=None):
		return set_units._create_units(set_type or self.set_type, count, make_department(), 300)

	def footprint(self):
		return {
			"units": frappe.db.count("Set Unit"),
			"codes": frappe.db.count("Code Registry"),
			"keys": frappe.db.count("Idempotency Key"),
			"audit": frappe.db.count("Audit Log"),
			"jobs": frappe.db.count("Print Job"),
		}

	def mark(self, job, status):
		core_print.ack(job, status, "Printer", error=None if status == "Printed" else "x")

	def assert_reject(self, result, response, code, status):
		self.assertFalse(result["ok"], msg=code)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(result["error"]["http_status"], status)
		self.assertEqual(response.get("http_status_code"), status, msg=code)
		self.assertEqual(last_reject().reason, code)


class TestCreateBatchRpc(SetUnitRpcCase):
	def test_create_batch_roles_before_any_write(self):
		unit = self.units(1)[0]
		nobody = make_user("t5-nobody@example.com")  # tạo tài khoản ghi Audit Log: dựng trước khi đo
		before = self.footprint()
		calls = (
			(api.create_batch, {"set_type": self.set_type, "count": 1}),
			(api.print_tags, {"set_units": [unit], "kinds": ["tag"], "tag_printer": self.printer}),
			(api.reprint_tag, {"set_unit": unit, "kind": "tag", "printer": self.printer, "reason": "x"}),
			(api.cancel_print, {"set_unit": unit, "reason": "x"}),
		)
		for user in (self.r04, self.r01, nobody):
			frappe.set_user(user)
			for fn, kwargs in calls:
				with self.assertRaises(frappe.PermissionError, msg=(user, fn.__name__)):
					post(fn, client_ts=TS, **kwargs)
			for fn, kwargs in (
				(api.tag_preview, {"set_unit": unit, "kind": "tag"}),
				(api.print_status, {"names": ["1"]}),
				(api.batch_csv, {"set_units": [unit]}),
			):
				with self.assertRaises(frappe.PermissionError, msg=(user, fn.__name__)):
					get(fn, **kwargs)
		frappe.set_user(self.r01)
		with self.assertRaises(frappe.PermissionError):
			post(api.verify_tag, set_unit=unit, raw=unit, client_ts=TS)
		frappe.set_user("Administrator")
		self.assertEqual(self.footprint(), before)

	@bru("BRU-ID-006")
	def test_create_batch_issues_and_queues_prints(self):
		frappe.set_user(self.r02)
		with patch.object(
			set_tags.print_server,
			"enqueue_server_dispatch_many",
			wraps=set_tags.print_server.enqueue_server_dispatch_many,
		) as dispatch:
			result, response = post(
				api.create_batch,
				set_type=self.set_type,
				count="3",
				kinds='["tray", "tag"]',
				tag_printer=self.printer,
				tray_printer=self.printer,
				client_ts=TS,
			)
		self.assertTrue(result["ok"])
		self.assertIsNone(response.get("http_status_code"))
		self.assertEqual(set(result), {"ok", "set_type", "set_ids", "jobs", "warnings"})
		self.assertEqual(result["set_type"], self.set_type)
		set_ids = result["set_ids"]
		self.assertEqual(len(set_ids), 3)
		for set_id in set_ids:
			self.assertEqual(gs1.parse_scan(gs1.giai_hri(set_id))["id"], set_id)
			self.assertEqual(frappe.db.get_value("Set Unit", set_id, "status"), "New")
		self.assertEqual(
			[(job["set_unit"], job["kind"]) for job in result["jobs"]],
			[(set_id, kind) for set_id in set_ids for kind in ("tag", "tray")],
		)
		self.assertEqual({job["status"] for job in result["jobs"]}, {"Queued"})
		dispatch.assert_called_once_with([job["print_job"] for job in result["jobs"]])
		self.assertEqual(result["warnings"], [])

	def test_create_batch_without_printing(self):
		frappe.set_user(self.r02)
		jobs_before = frappe.db.count("Print Job")
		for kinds in (None, "", "[]", []):
			result, _response = post(
				api.create_batch, set_type=self.set_type, count=2, kinds=kinds, client_ts=TS
			)
			self.assertTrue(result["ok"], msg=repr(kinds))
			self.assertEqual(len(result["set_ids"]), 2)
			self.assertEqual(result["jobs"], [])
		self.assertEqual(frappe.db.count("Print Job"), jobs_before)
		self.assertEqual(self.dispatch_calls(), [])

	@bru("BRU-ID-001")
	def test_create_batch_takes_no_prefix_from_the_form(self):
		"""A-13 G5: tiền tố GS1 chỉ lấy từ cấu hình site; người dùng không nhập được qua RPC."""
		import inspect

		parameters = set(inspect.signature(api.create_batch).parameters)
		self.assertFalse({"prefix", "company_prefix", "tc_gs1_company_prefix"} & parameters)
		self.assertIn("estimate_reason", parameters)

	def test_create_batch_existing_sets_and_warning(self):
		"""UC-03 A1 (AC-8): bộ đang lưu hành có số chu trình ước tính kèm lý do; cơ số > nguồn → chặn (A-13 G5, G6)."""
		frappe.set_user(self.r02)
		result, _response = post(
			api.create_batch,
			set_type=self.set_type,
			count=1,
			max_cycles="600",
			origin="Existing",
			cycles_used="120",
			estimate_reason="Đếm từ sổ giấy",
			client_ts=TS,
		)
		self.assert_reject(result, _response, "MAX_CYCLES_INVALID", 422)  # nguồn cơ số thấp hơn 600
		result, _response = post(
			api.create_batch,
			set_type=self.set_type,
			count=1,
			max_cycles="200",
			origin="Existing",
			cycles_used="120",
			estimate_reason="Đếm từ sổ giấy",
			client_ts=TS,
		)
		self.assertTrue(result["ok"])
		row = frappe.db.get_value(
			"Set Unit", result["set_ids"][0], ["cycles_used", "cycles_source", "max_cycles"], as_dict=True
		)
		self.assertEqual((row.cycles_used, row.cycles_source, row.max_cycles), (120, "Estimate", 200))
		self.assertEqual(result["warnings"], [])

	def test_create_batch_reject_bodies_and_http_status(self):
		frappe.set_user(self.r02)
		no_bom = make_set_type("TFIVENB").name
		cases = [
			({"count": count}, "COUNT_OUT_OF_RANGE", 422)
			for count in (0, -1, 101, "0", "101", "2.5", "1e2", "-1", "abc", 10**9, "9" * 5000)
		]
		cases += [
			({"set_type": no_bom}, "SET_TYPE_BOM_INVALID", 422),
			({"department": "Khoa không có T5"}, "DEPARTMENT_INVALID", 422),
			({"max_cycles": 0}, "MAX_CYCLES_INVALID", 422),
			({"max_cycles": "abc"}, "MAX_CYCLES_INVALID", 422),
			({"max_cycles": "9" * 5000}, "MAX_CYCLES_INVALID", 422),
			({"origin": "Existing", "cycles_used": "9" * 5000}, "MAX_CYCLES_INVALID", 422),
			({"origin": "Existing", "cycles_used": 300, "max_cycles": 300}, "MAX_CYCLES_INVALID", 422),
			({"origin": "Existing", "cycles_used": 5, "max_cycles": 100}, "REASON_REQUIRED", 422),
			(
				{"origin": "Existing", "cycles_used": 0, "max_cycles": 100, "estimate_reason": "x"},
				"MAX_CYCLES_INVALID",
				422,
			),
			({"set_type": "NOPE-T5"}, "SET_TYPE_NOT_FOUND", 404),
		]
		before = self.footprint()
		for overrides, code, status in cases:
			kwargs = {"set_type": self.set_type, "count": 2, "client_ts": TS, **overrides}
			result, response = post(api.create_batch, **kwargs)
			self.assert_reject(result, response, code, status)
			log = last_reject()
			self.assertEqual(log.ref_doctype, "Instrument Set Type", msg=code)
			self.assertEqual(log.ref_name, kwargs["set_type"], msg=code)
			if code == "SET_TYPE_BOM_INVALID":
				self.assertEqual(result["error"]["items"][0]["code"], "NO_EFFECTIVE_BOM")
		conf, flags = production_site(tc_gs1_company_prefix=gs1.DEFAULT_COMPANY_PREFIX)
		with conf, flags:
			result, response = post(api.create_batch, set_type=self.set_type, count=1, client_ts=TS)
		self.assert_reject(result, response, "GS1_PREFIX_NOT_CONFIGURED", 409)
		after = self.footprint()
		self.assertEqual(
			{key: after[key] for key in ("units", "codes", "jobs")},
			{key: before[key] for key in ("units", "codes", "jobs")},
		)

	def test_create_batch_template_broken_issues_nothing(self):
		frappe.set_user("Administrator")
		template = core_print.active_template("Set Tag", None).name
		frappe.db.set_value("Label Template", template, "body", "{{ doc.set_id | nope_filter }}")
		frappe.set_user(self.r02)
		before = self.footprint()
		result, response = post(
			api.create_batch,
			set_type=self.set_type,
			count=3,
			kinds=["tag"],
			tag_printer=self.printer,
			client_ts=TS,
		)
		self.assert_reject(result, response, "LABEL_RENDER_FAILED", 422)
		self.assertEqual(frappe.db.count("Set Unit", {"set_type": self.set_type}), 0)
		self.assertEqual(frappe.db.count("Code Registry"), before["codes"])
		self.assertEqual(frappe.db.count("Print Job"), before["jobs"])

	def test_create_batch_bad_params_400(self):
		frappe.set_user(self.r02)
		inactive = self.make_printer()
		frappe.db.set_value("Printer", inactive, "is_active", 0)
		good = {"set_type": self.set_type, "count": 1, "client_ts": TS}
		bad = (
			{"kinds": '["label"]', "tag_printer": self.printer},
			{"kinds": "not json"},
			{"kinds": 5},
			{"kinds": [["tag"]]},
			{"kinds": ["tag"]},
			{"kinds": ["tag", "tray"], "tag_printer": self.printer},
			{"kinds": ["tag"], "tag_printer": inactive},
			{"kinds": ["tag"], "tag_printer": "PRN-NONE-T5"},
			{"kinds": ["tag"], "tag_printer": 5},
			{"set_type": None},
			{"set_type": ""},
			{"set_type": 5},
			{"count": None},
			{"count": True},
			{"count": 2.5},
			{"count": [1]},
			{"origin": "Old"},
			{"origin": None},
			{"department": 5},
			{"max_cycles": 2.5},
			{"max_cycles": True},
			{"cycles_used": [1]},
			{"cycles_used": False},
		)
		before = self.footprint()
		for overrides in bad:
			with self.assertRaises(BadRequestError, msg=repr(overrides)):
				post(api.create_batch, **{**good, **overrides})
		self.assertEqual(self.footprint(), before)

	def test_create_batch_agent_only_printer_refused(self):
		"""Ruling Task 4/5: thẻ/nhãn khay chỉ in qua đường server — máy in không có địa chỉ mạng → 422, không cấp."""
		frappe.set_user(self.r02)
		agent = self.make_printer(host="")
		before = self.footprint()
		result, response = post(
			api.create_batch,
			set_type=self.set_type,
			count=2,
			kinds=["tag", "tray"],
			tag_printer=self.printer,
			tray_printer=agent,
			client_ts=TS,
		)
		self.assert_reject(result, response, "PRINTER_NOT_NETWORK", 422)
		self.assertEqual(result["error"]["items"], [agent])
		self.assertEqual(frappe.db.count("Set Unit"), before["units"])
		self.assertEqual(frappe.db.count("Print Job"), before["jobs"])

	@bru("BRU-ID-001")
	def test_create_batch_replay_same_key_same_set_ids(self):
		frappe.set_user(self.r02)
		key = str(uuid.uuid4())
		kwargs = {
			"set_type": self.set_type,
			"count": 2,
			"kinds": ["tag"],
			"tag_printer": self.printer,
			"client_ts": TS,
		}
		first, _response = post(api.create_batch, key, **kwargs)
		after_first = self.footprint()
		second, _response = post(api.create_batch, key, **kwargs)
		self.assertEqual(first, second)
		self.assertEqual(len(first["set_ids"]), 2)
		self.assertEqual(self.footprint(), after_first)
		self.assertEqual(frappe.db.count("Set Unit", {"set_type": self.set_type}), 2)


class TestPrintRpc(SetUnitRpcCase):
	def test_print_tags_needs_reprint_for_printed_units(self):
		printed, failed = self.units(2)
		frappe.set_user(self.r10)
		result, _response = post(
			api.print_tags,
			set_units=[printed, failed],
			kinds='["tag"]',
			tag_printer=self.printer,
			client_ts=TS,
		)
		self.assertTrue(result["ok"])
		self.assertEqual(set(result), {"ok", "jobs", "warnings"})
		jobs = [job["print_job"] for job in result["jobs"]]
		self.mark(jobs[0], "Printed")
		self.mark(jobs[1], "Failed")

		result, response = post(
			api.print_tags, set_units=[printed, failed], kinds=["tag"], tag_printer=self.printer, client_ts=TS
		)
		self.assert_reject(result, response, "REASON_REQUIRED", 422)
		self.assertEqual(result["error"]["items"], [{"set_unit": printed, "kind": "tag"}])
		self.assertEqual(last_reject().ref_name, printed)

		result, _response = post(  # in bù: mọi job trước Failed → không cần lý do
			api.print_tags, set_units=f'["{failed}"]', kinds=["tag"], tag_printer=self.printer, client_ts=TS
		)
		self.assertTrue(result["ok"])
		result, response = post(
			api.print_tags, set_units=[failed], kinds=["tag"], tag_printer=self.printer, client_ts=TS
		)
		self.assert_reject(result, response, "TAG_PRINT_PENDING", 409)

		agent = self.make_printer(host="")
		result, response = post(
			api.print_tags, set_units=[failed], kinds=["tray"], tray_printer=agent, client_ts=TS
		)
		self.assert_reject(result, response, "PRINTER_NOT_NETWORK", 422)

		for bad in (
			{"set_units": []},
			{"set_units": "nope"},
			{"set_units": [5]},
			{"set_units": [f"9520000TFIVE{i:06d}" for i in range(101)]},
			{"set_units": [printed], "kinds": []},
			{"set_units": [printed], "kinds": ["label"]},
			{"set_units": [printed], "tag_printer": None},
		):
			kwargs = {"kinds": ["tag"], "tag_printer": self.printer, "client_ts": TS, **bad}
			with self.assertRaises(BadRequestError, msg=repr(bad)):
				post(api.print_tags, **kwargs)

	@bru("BRU-ID-001")
	def test_reprint_tag_rpc(self):
		unit, disposed = self.units(2)
		frappe.set_user(self.r10)
		first, _response = post(
			api.print_tags, set_units=[unit], kinds=["tag"], tag_printer=self.printer, client_ts=TS
		)
		self.mark(first["jobs"][0]["print_job"], "Printed")

		for reason in ("", "   ", None, "x" * 501):
			result, response = post(
				api.reprint_tag, set_unit=unit, kind="tag", printer=self.printer, reason=reason, client_ts=TS
			)
			self.assert_reject(result, response, "REASON_REQUIRED", 422)

		warnings = []
		for reason in ("Thẻ rơi khi hấp", "Thẻ mờ", "Thẻ lỗi - không đọc được"):
			result, _response = post(
				api.reprint_tag, set_unit=unit, kind="tag", printer=self.printer, reason=reason, client_ts=TS
			)
			self.assertTrue(result["ok"])
			self.assertEqual(set(result), {"ok", "print_job", "status", "warning", "counts"})
			self.assertEqual(result["status"], "Queued")
			self.assertEqual(frappe.db.get_value("Print Job", result["print_job"], "reprint_reason"), reason)
			self.assertEqual(result["counts"]["tag"]["pending"], 1)
			warnings.append(result["warning"] and result["warning"]["code"])
			self.mark(result["print_job"], "Printed")
		self.assertEqual(warnings, [None, None, "TAG_REPRINTED"])
		self.assertEqual(result["counts"]["tag"]["reprints"], 3)

		frappe.set_user("Administrator")
		frappe.db.set_value("Set Unit", disposed, "status", "Disposed")
		frappe.set_user(self.r10)
		result, response = post(
			api.reprint_tag, set_unit=disposed, kind="tag", printer=self.printer, reason="x", client_ts=TS
		)
		self.assert_reject(result, response, "SET_DISPOSED", 409)
		for bad in ({"kind": "label"}, {"kind": None}, {"printer": None}, {"set_unit": 5}):
			kwargs = {"set_unit": unit, "kind": "tag", "printer": self.printer, "reason": "x", **bad}
			with self.assertRaises(BadRequestError, msg=repr(bad)):
				post(api.reprint_tag, client_ts=TS, **kwargs)

		frappe.set_user(self.r04)
		before = self.footprint()
		with self.assertRaises(frappe.PermissionError):
			post(api.reprint_tag, set_unit=unit, kind="tag", printer=self.printer, reason="x", client_ts=TS)
		frappe.set_user("Administrator")
		self.assertEqual(self.footprint(), before)

	def test_cancel_print_releases_stuck_jobs(self):
		"""Ruling Task 4/5: job Waiting (máy in agent cũ) / Queued của máy in đã tắt không chặn bộ mãi mãi."""
		unit, other = self.units(2)
		stuck = core_print.create_job(
			STATION,
			None,
			{"label_object": "Set Tag", "set_unit": unit, "kind": "tag", "reprint": False},
			core_print.active_template("Set Tag", None).name,
			printer=self.make_printer(host=""),
			status="Waiting",
			ref_doctype="Set Unit",
			ref_name=unit,
		)
		frappe.set_user(self.r02)
		result, response = post(
			api.print_tags, set_units=[unit], kinds=["tag"], tag_printer=self.printer, client_ts=TS
		)
		self.assert_reject(result, response, "TAG_PRINT_PENDING", 409)

		for reason in (None, "", "  ", "x" * 501):
			result, response = post(api.cancel_print, set_unit=unit, reason=reason, client_ts=TS)
			self.assert_reject(result, response, "REASON_REQUIRED", 422)
		result, response = post(api.cancel_print, set_unit="9520000TFIVE999999", reason="x", client_ts=TS)
		self.assert_reject(result, response, "SET_NOT_FOUND", 404)
		for bad in ({"set_unit": 5}, {"set_unit": unit, "kind": "label"}):
			with self.assertRaises(BadRequestError, msg=repr(bad)):
				post(api.cancel_print, reason="x", client_ts=TS, **bad)

		result, _response = post(api.cancel_print, set_unit=unit, reason=" Máy in agent cũ ", client_ts=TS)
		self.assertTrue(result["ok"])
		self.assertEqual(result["cancelled"], [stuck])
		self.assertEqual(result["counts"]["tag"]["pending"], 0)
		row = frappe.db.get_value("Print Job", stuck, ["status", "error"], as_dict=True)
		self.assertEqual(row.status, "Failed")
		self.assertIn("Máy in agent cũ", row.error)
		audit = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Print Job", "ref_name": stuck, "action": "Update"},
			fields=["reason", "old_value", "new_value"],
		)
		self.assertEqual(len(audit), 1)
		self.assertEqual(audit[0].reason, "Máy in agent cũ")
		self.assertEqual(frappe.parse_json(audit[0].old_value), {"status": "Waiting"})
		self.assertEqual(frappe.parse_json(audit[0].new_value)["status"], "Failed")

		# in bù sau khi hủy: không cần lý do
		result, _response = post(
			api.print_tags,
			set_units=[unit, other],
			kinds=["tag", "tray"],
			tag_printer=self.printer,
			tray_printer=self.printer,
			client_ts=TS,
		)
		self.assertTrue(result["ok"])
		queued = {(job["set_unit"], job["kind"]): job["print_job"] for job in result["jobs"]}

		# máy in bị tắt sau khi job Queued: cron bỏ qua mãi → hủy theo loại
		frappe.set_user("Administrator")
		frappe.db.set_value("Printer", self.printer, "is_active", 0)
		frappe.set_user(self.r10)
		result, _response = post(
			api.cancel_print, set_unit=unit, kind="tray", reason="Máy in tắt", client_ts=TS
		)
		self.assertEqual(result["cancelled"], [queued[(unit, "tray")]])
		self.assertEqual(frappe.db.get_value("Print Job", queued[(unit, "tag")], "status"), "Queued")
		self.assertEqual(frappe.db.get_value("Print Job", queued[(unit, "tray")], "status"), "Failed")
		result, _response = post(api.cancel_print, set_unit=unit, reason="Máy in tắt", client_ts=TS)
		self.assertEqual(result["cancelled"], [queued[(unit, "tag")]])
		result, _response = post(api.cancel_print, set_unit=unit, reason="Máy in tắt", client_ts=TS)
		self.assertEqual(result["cancelled"], [])  # không còn job chờ: không lỗi
		self.assertEqual(frappe.db.get_value("Print Job", queued[(other, "tag")], "status"), "Queued")


class TestVerifyPreviewStatusCsv(SetUnitRpcCase):
	@bru("BRU-ID-006")
	def test_verify_tag_rpc_r04_allowed(self):
		unit, other = self.units(2)
		frappe.set_user(self.r04)
		result, _response = post(api.verify_tag, set_unit=unit, raw=f"]d2\x1d8004{unit}\r\n", client_ts=TS)
		self.assertTrue(result["ok"])
		self.assertEqual(result["set_unit"], unit)
		self.assertTrue(result["verified_on"])
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "tag_verified_by"), self.r04)

		result, response = post(api.verify_tag, set_unit=unit, raw=gs1.giai_hri(other), client_ts=TS)
		self.assert_reject(result, response, "TAG_MISMATCH", 409)
		log = last_reject()
		self.assertEqual((log.ref_doctype, log.ref_name), ("Set Unit", unit))
		self.assertEqual(frappe.parse_json(log.new_value)["raw"], gs1.giai_hri(other))
		self.assertEqual(result["error"]["items"], [{"expected": unit, "scanned": other}])

		result, response = post(api.verify_tag, set_unit=unit, raw="XYZ", client_ts=TS)
		self.assert_reject(result, response, "SCAN_INVALID", 422)
		result, response = post(api.verify_tag, set_unit="9520000TFIVE999999", raw=unit, client_ts=TS)
		self.assert_reject(result, response, "SET_NOT_FOUND", 404)

	def test_tag_preview_get_only_and_shape(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[api.tag_preview], ["GET"])
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[api.print_status], ["GET"])
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[api.batch_csv], ["GET"])
		for fn in (api.create_batch, api.print_tags, api.reprint_tag, api.verify_tag, api.cancel_print):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"], msg=fn.__name__)
		unit, disposed = self.units(2)
		frappe.set_user(self.r02)
		for kind in ("tag", "tray"):
			result, response = get(api.tag_preview, set_unit=unit, kind=kind)
			self.assertEqual(set(result), {"ok", "png_b64", "zpl", "hri"})
			self.assertTrue(result["ok"])
			self.assertTrue(base64.b64decode(result["png_b64"]).startswith(b"\x89PNG"))
			self.assertIn(f"^FD_18004{unit}^FS", result["zpl"])
			self.assertEqual(result["hri"], gs1.giai_hri(unit))
			self.assertFalse(response["_commit"])  # xem trước không ghi gì

		frappe.set_user("Administrator")
		frappe.db.set_value("Set Unit", disposed, "status", "Disposed")
		frappe.set_user(self.r02)
		result, response = get(api.tag_preview, set_unit=disposed, kind="tag")
		self.assert_reject(result, response, "SET_DISPOSED", 409)
		self.assertTrue(response["_commit"])  # GET: dòng Audit Reject phải được commit
		result, response = get(api.tag_preview, set_unit="9520000TFIVE999999", kind="tag")
		self.assert_reject(result, response, "SET_NOT_FOUND", 404)
		conf, flags = production_site(tc_gs1_company_prefix=REAL_PREFIX)
		with conf, flags:
			result, response = get(api.tag_preview, set_unit=unit, kind="tag")
		self.assert_reject(result, response, "GS1_PREFIX_NOT_CONFIGURED", 409)
		for bad in ({"kind": "label"}, {"kind": None}, {"set_unit": None}, {"set_unit": 5}):
			with self.assertRaises(BadRequestError, msg=repr(bad)):
				get(api.tag_preview, **{"set_unit": unit, "kind": "tag", **bad})

	def test_print_status_only_set_unit_jobs(self):
		unit = self.units(1)[0]
		frappe.set_user(self.r02)
		result, _response = post(
			api.print_tags,
			set_units=[unit],
			kinds=["tag", "tray"],
			tag_printer=self.printer,
			tray_printer=self.printer,
			client_ts=TS,
		)
		tag_job, tray_job = (job["print_job"] for job in result["jobs"])
		self.mark(tag_job, "Printed")
		frappe.set_user("Administrator")
		other = core_print.create_job(STATION, "^XA^XZ", {"label_object": "Station", "code": STATION})
		frappe.set_user(self.r02)

		result, response = get(
			api.print_status, names=frappe.as_json([tag_job, int(tray_job), other, "999999999"])
		)
		self.assertTrue(result["ok"])
		self.assertEqual(set(result["jobs"]), {tag_job, tray_job})
		tag = result["jobs"][tag_job]
		self.assertEqual(set(tag), {"status", "attempts", "error", "printed_at", "set_unit", "kind"})
		self.assertEqual(
			(tag["status"], tag["set_unit"], tag["kind"], tag["attempts"]), ("Printed", unit, "tag", 1)
		)
		self.assertTrue(tag["printed_at"])
		tray = result["jobs"][tray_job]
		self.assertEqual((tray["status"], tray["kind"], tray["printed_at"]), ("Queued", "tray", None))
		self.assertFalse(response["_commit"])
		self.assertEqual(api.MAX_STATUS_JOBS, 200)
		get(api.print_status, names=[str(i) for i in range(1, 201)])
		for bad in ([], [str(i) for i in range(1, 202)], "nope", [None], [True]):
			with self.assertRaises(BadRequestError, msg=repr(bad)):
				get(api.print_status, names=bad)

	@bru("BRU-ID-001")
	def test_batch_csv_columns_injection_and_demo_guard(self):
		injected = self.make_type("TFIVECSV", set_type_name="=HYPERLINK(1)")
		units = self.units(2, injected)
		frappe.set_user(self.r02)
		result, response = get(api.batch_csv, set_units=frappe.as_json(units))
		self.assertIsNone(result)
		self.assertEqual(response.type, "download")
		self.assertRegex(response.filename, r"^set-ids-\d{8}-\d{4}\.csv$")
		content = response.filecontent
		self.assertIsInstance(content, bytes)
		self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
		rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
		self.assertEqual(
			rows[0], ["set_id", "hri", "element_string", "set_type", "set_type_name", "department"]
		)
		department = frappe.db.get_value("Department", make_department(), "department_name")
		self.assertEqual(
			rows[1:],
			[
				[unit, gs1.giai_hri(unit), gs1.giai_hri(unit), injected, "'=HYPERLINK(1)", department]
				for unit in units
			],
		)
		self.assertTrue(response["_commit"])  # GET: dòng Audit export phải được commit
		log = frappe.get_all(
			"Audit Log",
			filters={"action": "Create", "ref_doctype": "Set Unit", "reason": "export"},
			fields=["ref_name", "new_value"],
			order_by="name desc",
			limit=1,
		)[0]
		self.assertEqual(log.ref_name, units[0])
		self.assertEqual(frappe.parse_json(log.new_value), {"count": 2, "set_ids": units})

		self.assertEqual(api._csv_cell("-1+1"), "'-1+1")
		self.assertEqual(api._csv_cell("@SUM(A1)"), "'@SUM(A1)")
		self.assertEqual(api._csv_cell("+1"), "'+1")
		self.assertEqual(api._csv_cell("\tx"), "'\tx")
		self.assertEqual(api._csv_cell("Khoa Ngoại"), "Khoa Ngoại")

		conf, flags = production_site(tc_gs1_company_prefix=REAL_PREFIX)
		with conf, flags:
			result, response = get(api.batch_csv, set_units=units)
		self.assert_reject(result, response, "GS1_PREFIX_NOT_CONFIGURED", 409)
		self.assertIsNone(response.get("filecontent"))
		result, response = get(api.batch_csv, set_units=[units[0], "9520000TFIVE999999"])
		self.assert_reject(result, response, "SET_NOT_FOUND", 404)
		for bad in ([], "nope", [5], [f"9520000TFIVE{i:06d}" for i in range(101)]):
			with self.assertRaises(BadRequestError, msg=repr(bad)):
				get(api.batch_csv, set_units=bad)


# ---------------------------------------------------------------------------------------------------------------------
# FEAT-016 Task 6: ngữ cảnh form, lịch sử vòng đời, thanh lý (FR-M1-06, FR-M1-06.2, FR-M1-05.2; BRU-ID-001; G7, G13, G14)
# ---------------------------------------------------------------------------------------------------------------------


class TestLifecycleRpc(SetUnitRpcCase):
	def test_lifecycle_rpcs_keep_set_unit_paths(self):
		from tracecore.v1 import set_unit_lifecycle

		for name in ("form_context", "history"):
			fn = frappe.get_attr(f"tracecore.v1.set_unit.{name}")
			self.assertIs(fn, getattr(set_unit_lifecycle, name))
			self.assertIn(fn, frappe.whitelisted, msg=name)
		self.assertEqual(api.ISSUE_ROLES, set_unit_lifecycle.ISSUE_ROLES)
		self.assertFalse(hasattr(set_unit_lifecycle, "dispose"))  # thanh lý hoãn sang FEAT-032 (A-13 G14)

	def test_form_context_permissions_by_role(self):
		nobody = make_user("t6-nobody@example.com")  # tạo trước khi đổi người dùng (chỉ R10 tạo tài khoản)
		unit = self.units(1)[0]
		expected = {
			self.r04: dict.fromkeys(("can_issue", "can_print", "can_reprint"), False) | {"can_verify": True},
			self.r02: dict.fromkeys(("can_issue", "can_print", "can_reprint", "can_verify"), True),
			self.r10: dict.fromkeys(("can_issue", "can_print", "can_reprint", "can_verify"), True),
			self.r01: dict.fromkeys(("can_issue", "can_print", "can_reprint", "can_verify"), False),
		}
		for user, permissions in expected.items():
			frappe.set_user(user)
			result, _response = get(api.form_context, set_unit=unit)
			self.assertTrue(result["ok"], msg=user)
			self.assertEqual(result["permissions"], permissions, msg=user)
			self.assertEqual(result["summary"]["set_id"], unit)
			self.assertEqual(
				result["limits"],
				{"max_batch": 100, "reason_max": 500, "max_cycles_limit": 99999},
			)
			self.assertEqual([k["kind"] for k in result["kinds"]], ["tag", "tray"])
			hint = [p["name"] for p in result["printers_hint"]]
			if permissions["can_print"]:
				self.assertIn(self.printer, hint)
			else:
				self.assertEqual(hint, [])
		frappe.set_user(self.r02)
		result, _response = get(api.form_context)
		self.assertIsNone(result["summary"])  # form "Cấp Set ID" chưa có bộ
		frappe.set_user(nobody)
		with self.assertRaises(frappe.PermissionError):
			get(api.form_context, set_unit=unit)
		with self.assertRaises(frappe.PermissionError):
			get(api.history, set_unit=unit)

	def test_form_context_test_labels_flag(self):
		"""Desk báo "nhãn có dòng TEST" (G3): theo tiền tố trong Set ID của bộ, hoặc tiền tố site khi chưa có bộ."""
		unit = self.units(1)[0]
		frappe.set_user(self.r02)
		result, _response = get(api.form_context, set_unit=unit)
		self.assertIs(result["test_labels"], gs1.is_demo_prefix(unit))
		self.assertTrue(result["test_labels"])  # site test dùng dải demo 952
		result, _response = get(api.form_context)
		self.assertIs(result["test_labels"], True)
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": REAL_PREFIX}):
			result, _response = get(api.form_context)
			self.assertIs(result["test_labels"], False)
			# bộ đã cấp giữ tiền tố trong mã của nó
			result, _response = get(api.form_context, set_unit=unit)
			self.assertIs(result["test_labels"], True)

	def test_history_unknown_set_404_with_audit_commit(self):
		for fn in (api.history, api.form_context):
			result, response = get(fn, set_unit="9520000TFIVE999999")
			self.assert_reject(result, response, "SET_NOT_FOUND", 404)
			self.assertTrue(response["_commit"])  # GET: dòng Audit Reject phải được commit

		unit = self.units(1)[0]
		step_gate.start_cycle(unit)
		result, response = get(api.history, set_unit=unit, limit="1")
		self.assertTrue(result["ok"])
		self.assertEqual([e["event"] for e in result["events"]], ["start_cycle"])
		self.assertFalse(response["_commit"])  # đọc thành công không ghi gì
		older, _response = get(api.history, set_unit=unit, before=result["next_before"], limit=50)
		self.assertEqual([e["event"] for e in older["events"]], ["issue"])
		self.assertIsNone(older["next_before"])
		for bad in ({"limit": "0"}, {"limit": "abc"}, {"limit": 201}, {"limit": True}, {"before": "nope"}):
			with self.assertRaises(BadRequestError, msg=repr(bad)):
				get(api.history, set_unit=unit, **bad)
		with self.assertRaises(BadRequestError):
			get(api.history, set_unit=None)
