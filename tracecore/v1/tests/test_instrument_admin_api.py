"""RPC tracecore.v1.instrument_admin.* (FEAT-014 Task 4): khởi tạo bộ đếm bảo dưỡng và ngừng sử dụng dụng cụ.

Quyền R02/R10/System Manager kiểm trước mọi ghi; từ chối nghiệp vụ trả body chuẩn + mã HTTP + Audit Log `Reject`
(A-06 I6, I13, I15).
"""

import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe

from tracecore.core.errors import HTTP_STATUS
from tracecore.instrument import catalog
from tracecore.tests.factories import (
	make_bom,
	make_instrument,
	make_maintenance,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import instrument_admin as admin_api

# Instrument/Set Unit/Instrument Maintenance liên kết Item, Batch, Department, User, Employee; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def now_ts():
	return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def call(fn, key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4())}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def as_user(roles, fn, **kwargs):
	email = make_user(
		f"instr-admin-{'-'.join(r.lower().replace(' ', '') for r in roles) or 'none'}@example.com", roles
	)
	frappe.set_user(email)
	try:
		return call(fn, **kwargs)
	finally:
		frappe.set_user("Administrator")


def _counter(set_unit, instrument):
	return frappe.db.get_value(
		"Instrument Maintenance", {"set_unit": set_unit, "instrument": instrument}, "cycles_since_maint"
	)


class TestInitCountersRpc(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		make_instrument("IA-CNT", interval=40, maint_type="Blade Check")
		self.set_type = make_set_type("IAC")
		make_bom(self.set_type, [("IA-CNT", 1)])
		self.units = [make_set_unit(self.set_type.name).name for _i in range(3)]

	@bru("BRU-REP-014")
	def test_init_counters_rpc_roles_and_atomic(self):
		rows = [
			{"set_unit": self.units[0], "cycles_since": 37, "last_maint_on": "2026-09-01"},
			{"set_unit": self.units[1], "cycles_since": 5, "last_maint_on": None},
		]
		# R04: PermissionError trước mọi ghi
		keys, audit_rows = (
			frappe.db.count("Idempotency Key"),
			frappe.db.count("Audit Log", {"ref_doctype": ["!=", "User"]}),
		)
		with self.assertRaises(frappe.PermissionError):
			as_user(["TC R04"], admin_api.init_counters, instrument="IA-CNT", rows=rows, reason="Sổ cũ")
		self.assertEqual(frappe.db.count("Idempotency Key"), keys)
		self.assertEqual(frappe.db.count("Audit Log", {"ref_doctype": ["!=", "User"]}), audit_rows)
		self.assertIsNone(_counter(self.units[0], "IA-CNT"))

		# lỗi ở dòng 2 → không dòng nào được ghi
		rejects = frappe.db.count("Audit Log", {"action": "Reject", "reason": "COUNTER_INIT_INVALID"})
		bad = [rows[0], {"set_unit": self.units[1], "cycles_since": 10000}]
		result = as_user(["TC R02"], admin_api.init_counters, instrument="IA-CNT", rows=bad, reason="Sổ cũ")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "COUNTER_INIT_INVALID")
		self.assertEqual(result["error"]["items"][0]["row"], 2)
		self.assertEqual(http_status(), 422)
		self.assertIsNone(_counter(self.units[0], "IA-CNT"))
		self.assertEqual(
			frappe.db.count("Audit Log", {"action": "Reject", "reason": "COUNTER_INIT_INVALID"}), rejects + 1
		)

		# R02 thành công cả loạt; JSON dạng chuỗi như từ HTTP
		result = as_user(
			["TC R02"],
			admin_api.init_counters,
			instrument="IA-CNT",
			rows=frappe.as_json(rows),
			reason="Sổ cũ",
		)
		self.assertTrue(result["ok"])
		self.assertEqual(
			result["counters"],
			[
				{"set_unit": self.units[0], "instrument": "IA-CNT", "name": f"{self.units[0]}-IA-CNT"},
				{"set_unit": self.units[1], "instrument": "IA-CNT", "name": f"{self.units[1]}-IA-CNT"},
			],
		)
		self.assertEqual((_counter(self.units[0], "IA-CNT"), _counter(self.units[1], "IA-CNT")), (37, 5))

		# R10 và System Manager cũng được
		for roles, unit in ((["TC R10"], self.units[2]), (["System Manager"], self.units[2])):
			result = as_user(
				roles,
				admin_api.init_counters,
				instrument="IA-CNT",
				rows=[{"set_unit": unit, "cycles_since": 3}],
				reason="x",
			)
			self.assertTrue(result["ok"], roles)

	def test_init_counters_replay_same_key(self):
		key, ts = str(uuid.uuid4()), now_ts()
		kwargs = {
			"instrument": "IA-CNT",
			"rows": [{"set_unit": self.units[0], "cycles_since": 8}],
			"reason": "Sổ cũ",
			"client_ts": ts,
		}
		first = call(admin_api.init_counters, key=key, **kwargs)
		audit_rows = frappe.db.count("Audit Log", {"ref_doctype": ["!=", "User"]})
		second = call(admin_api.init_counters, key=key, **kwargs)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Audit Log", {"ref_doctype": ["!=", "User"]}), audit_rows)

	def test_init_counters_rejections(self):
		make_maintenance(self.units[0], "IA-CNT", cycles_since=2, deferred_count=1)
		cases = (
			(
				{
					"instrument": "IA-NONE",
					"rows": [{"set_unit": self.units[1], "cycles_since": 1}],
					"reason": "x",
				},
				"INSTRUMENT_NOT_FOUND",
				404,
			),
			(
				{
					"instrument": "IA-CNT",
					"rows": [{"set_unit": self.units[1], "cycles_since": 1}],
					"reason": "  ",
				},
				"REASON_REQUIRED",
				422,
			),
			({"instrument": "IA-CNT", "rows": [], "reason": "x"}, "COUNTER_INIT_INVALID", 422),
			(
				{
					"instrument": "IA-CNT",
					"rows": [{"set_unit": self.units[0], "cycles_since": 1}],
					"reason": "x",
				},
				"COUNTER_INIT_INVALID",
				422,
			),
			(
				{
					"instrument": "IA-CNT",
					"rows": [
						{"set_unit": self.units[1], "cycles_since": 1},
						{"set_unit": self.units[1], "cycles_since": 2},
					],
					"reason": "x",
				},
				"COUNTER_INIT_INVALID",
				422,
			),
			(
				{"instrument": "IA-CNT", "rows": [{"set_unit": "SU-NONE", "cycles_since": 1}], "reason": "x"},
				"SET_NOT_FOUND",
				404,
			),
		)
		for kwargs, code, status in cases:
			result = call(admin_api.init_counters, **kwargs)
			self.assertEqual(result["error"]["code"], code, kwargs)
			self.assertEqual(http_status(), status, kwargs)
		self.assertIsNone(_counter(self.units[1], "IA-CNT"))
		for rows in ("not json", [1, 2], {"set_unit": self.units[1]}):
			with self.assertRaises(frappe.ValidationError):
				call(admin_api.init_counters, instrument="IA-CNT", rows=rows, reason="x")

	def test_init_counters_bad_row_types_are_400(self):
		# set_unit không phải chuỗi (list/dict không băm được) → 400 trước khi kiểm trùng, không 500
		bad_rows = (
			[{"set_unit": [self.units[1]], "cycles_since": 1}],
			[{"set_unit": {"name": self.units[1]}, "cycles_since": 1}],
			[{"set_unit": self.units[1], "cycles_since": 1}, {"set_unit": ["x"], "cycles_since": 1}],
			[{"set_unit": 12, "cycles_since": 1}],
			[{"cycles_since": 1}],
			'[{"set_unit": ["a"], "cycles_since": 1}]',
		)
		for rows in bad_rows:
			with self.assertRaises(frappe.ValidationError, msg=repr(rows)):
				call(admin_api.init_counters, instrument="IA-CNT", rows=rows, reason="x")
		for instrument in (["IA-CNT"], {"a": 1}, 5):
			with self.assertRaises(frappe.ValidationError, msg=repr(instrument)):
				call(
					admin_api.init_counters,
					instrument=instrument,
					rows=[{"set_unit": self.units[1], "cycles_since": 1}],
					reason="x",
				)
		self.assertIsNone(_counter(self.units[1], "IA-CNT"))
		# số chu trình lạ qua RPC → 422, không 500
		for value in ("²", "1" * 5000):
			result = call(
				admin_api.init_counters,
				instrument="IA-CNT",
				rows=[{"set_unit": self.units[1], "cycles_since": value}],
				reason="x",
			)
			self.assertEqual(result["error"]["code"], "COUNTER_INIT_INVALID")
			self.assertEqual(http_status(), 422)

	def test_whitelisted_post_only(self):
		for fn in (admin_api.init_counters, admin_api.retire):
			self.assertIn(fn, frappe.whitelisted)
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"])


class TestRetireRpc(IsolatedTestCase):
	def test_retire_rpc_flow(self):
		make_instrument("IA-RET")
		set_type = make_set_type("IAR", set_type_name="Retire tray")
		make_bom(set_type, [("IA-RET", 1)])

		with self.assertRaises(frappe.PermissionError):
			as_user(["TC R04"], admin_api.retire, instrument="IA-RET", reason="Gãy")

		result = as_user(["TC R02"], admin_api.retire, instrument="IA-RET", reason="Gãy")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INSTRUMENT_IN_BOM")
		self.assertEqual(http_status(), 409)
		self.assertEqual([row["set_type"] for row in result["error"]["boms"]], ["IAR"])
		self.assertEqual(frappe.db.get_value("Instrument", "IA-RET", "status"), "Active")

		result = as_user(["TC R02"], admin_api.retire, instrument="IA-RET", reason=" Gãy ", confirm=1)
		self.assertTrue(result["ok"])
		self.assertEqual(result["instrument"]["status"], "Retired")
		self.assertEqual(result["instrument"]["retired_reason"], "Gãy")
		self.assertEqual([row["set_type"] for row in result["boms"]], ["IAR"])
		self.assertEqual(frappe.db.get_value("Instrument", "IA-RET", "status"), "Retired")

		again = call(admin_api.retire, instrument="IA-RET", reason="Gãy", confirm=1)
		self.assertEqual(again["error"]["code"], "INSTRUMENT_RETIRED")
		self.assertEqual(http_status(), 409)

	def test_retire_rpc_rejections_and_roles(self):
		make_instrument("IA-RFREE")
		for blank in ("", "  ", None):
			result = call(admin_api.retire, instrument="IA-RFREE", reason=blank)
			self.assertEqual(result["error"]["code"], "REASON_REQUIRED")
			self.assertEqual(http_status(), 422)
		result = call(admin_api.retire, instrument="IA-NOPE", reason="x")
		self.assertEqual(result["error"]["code"], "INSTRUMENT_NOT_FOUND")
		self.assertEqual(http_status(), 404)
		self.assertEqual(frappe.db.get_value("Instrument", "IA-RFREE", "status"), "Active")
		result = as_user(["TC R10"], admin_api.retire, instrument="IA-RFREE", reason="Mất", confirm="0")
		self.assertTrue(result["ok"])
		self.assertEqual(result["boms"], [])

	def test_retire_race_returns_409_block(self):
		# request song song đã ngừng sử dụng dụng cụ sau lúc RPC đọc trạng thái (Active) nhưng trước khi
		# catalog.retire khóa bản ghi: trả body INSTRUMENT_RETIRED 409 + Audit Log Reject, không ValidationError (417)
		make_instrument("IA-RACE")
		catalog.retire("IA-RACE", "Request khác")
		original = frappe.db.get_value

		def stale_status(*args, **kwargs):
			# chỉ lần RPC đọc trạng thái (trước khi khóa) thấy giá trị cũ
			if args[:3] == ("Instrument", "IA-RACE", "status") and not kwargs:
				return "Active"
			return original(*args, **kwargs)

		rejects = frappe.db.count("Audit Log", {"action": "Reject", "reason": "INSTRUMENT_RETIRED"})
		with patch.object(frappe.db, "get_value", side_effect=stale_status):
			result = call(admin_api.retire, instrument="IA-RACE", reason="Gãy", confirm=1)
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], "INSTRUMENT_RETIRED")
		self.assertEqual(http_status(), 409)
		self.assertEqual(
			frappe.db.count("Audit Log", {"action": "Reject", "reason": "INSTRUMENT_RETIRED"}), rejects + 1
		)
		self.assertEqual(frappe.db.get_value("Instrument", "IA-RACE", "retired_reason"), "Request khác")


class TestHttpStatus(IsolatedTestCase):
	def test_http_status_new_codes(self):
		self.assertEqual(HTTP_STATUS["COUNTER_INIT_INVALID"], 422)
		self.assertEqual(HTTP_STATUS["INSTRUMENT_RETIRED"], 409)
		self.assertEqual(HTTP_STATUS["INSTRUMENT_IN_BOM"], 409)
		self.assertEqual(HTTP_STATUS["INSTRUMENT_NOT_FOUND"], 404)
