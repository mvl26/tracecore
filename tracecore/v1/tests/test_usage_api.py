"""RPC tracecore.v1.usage.* (FEAT-027): quét sử dụng T8 qua phiên trạm thẻ nhân viên, mã HTTP, quyền, idempotent."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.reprocessing.tests.test_usage import issue
from tracecore.tests.factories import make_department, make_employee, make_stocked_pack, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import usage as usage_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-008"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
SESSION_TOKENS = {}


def as_administrator(fn, *args, **kwargs):
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user(user)


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, station_header=STATION, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	if fn is not usage_api.reveal_patient_code:
		kwargs.setdefault("token", SESSION_TOKENS.get(frappe.session.user))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": station_header}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def assert_block(case, result, code, status):
	case.assertIs(result["ok"], False)
	case.assertEqual(result["error"]["code"], code)
	case.assertEqual(result["error"]["http_status"], status)
	case.assertEqual(http_status(), status)


class UsageApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		SESSION_TOKENS.clear()
		self.addCleanup(SESSION_TOKENS.clear)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.dept = as_administrator(make_department, "Khoa API sử dụng")
		self.pack = as_administrator(self.issued_pack)
		self.nurse = self.as_user("khoa@example.com", ["TC R08"], self.dept)

	def issued_pack(self):
		return issue(make_stocked_pack(), self.dept)

	def as_user(self, email, roles, department=None, station=STATION):
		frappe.set_user("Administrator")
		user = make_user(email, roles=roles)
		employee = make_employee(first_name="Người dùng " + email, department=department or self.dept)
		frappe.db.set_value("Employee", employee.name, "user_id", user)
		SESSION_TOKENS[user] = make_station_session(user, station)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		return user

	def confirm_args(self, **kwargs):
		return {
			"cycle_id": self.pack.name,
			"station": STATION,
			"patient_code": "BN12345678",
			"surgery_code": "CA-API-1",
			"surgeon": "BS A",
			"room": "P2",
			**kwargs,
		}


class TestScanAndConfirm(UsageApiCase):
	@bru("BRU-FLOW-003")
	def test_scan_then_confirm_full_flow(self):
		card = call(usage_api.scan, raw=self.pack.name, station=STATION)
		self.assertTrue(card["ok"])
		self.assertEqual(card["card"]["cycle_id"], self.pack.name)
		done = call(usage_api.confirm, **self.confirm_args())
		self.assertTrue(done["ok"])
		self.assertEqual(done["patient_code_masked"], "BN1****678")
		self.assertNotIn("BN12345678", frappe.as_json(done))
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, "status"), "Used")

	@bru("BRU-ID-003")
	def test_used_pack_is_blocked_with_409_and_audit(self):
		call(usage_api.confirm, **self.confirm_args())
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		result = call(usage_api.scan, raw=self.pack.name, station=STATION)
		assert_block(self, result, "PACK_USED", 409)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before + 1)  # FR-M2-18.2
		again = call(usage_api.confirm, **self.confirm_args())
		assert_block(self, again, "PACK_USED", 409)

	def test_replay_with_same_key_returns_same_record(self):
		key = str(uuid.uuid4())
		stamp = now_ts()  # cùng khóa và cùng nội dung (kể cả client_ts) là một yêu cầu gửi lại
		first = call(usage_api.confirm, key, client_ts=stamp, **self.confirm_args())
		replay = call(usage_api.confirm, key, client_ts=stamp, **self.confirm_args())
		self.assertEqual(first["usage"], replay["usage"])
		self.assertEqual(frappe.db.count("Usage Record", {"pack": self.pack.name}), 1)

	def test_roles_and_station(self):
		other = self.as_user("capphat@example.com", ["TC R06"])
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			call(usage_api.scan, raw=self.pack.name, station=STATION)
		frappe.set_user(self.nurse)
		wrong = call(usage_api.scan, raw=self.pack.name, station="TR-007")
		self.assertFalse(wrong["ok"])  # phiên của TR-008 dùng ở trạm khác: SESSION_STATION_MISMATCH 403
		self.assertEqual(wrong["error"]["code"], "SESSION_STATION_MISMATCH")
		self.assertEqual(http_status(), 403)

	def test_emergency_then_patient_code(self):
		done = call(usage_api.confirm, **self.confirm_args(patient_code="", emergency=1))
		self.assertTrue(done["emergency"])
		later = call(
			usage_api.set_patient_code, usage=done["usage"], patient_code="BN55667788", station=STATION
		)
		self.assertEqual(later["patient_code_masked"], "BN5****788")


class TestReveal(UsageApiCase):
	def test_only_r01_r02_and_system_manager_reveal(self):
		usage = call(usage_api.confirm, **self.confirm_args())["usage"]
		with self.assertRaises(frappe.PermissionError):
			call(usage_api.reveal_patient_code, usage=usage, reason="thử")  # R08 không xem được
		frappe.set_user("Administrator")
		reviewer = make_user("r02-usage@example.com", roles=["TC R02"])
		frappe.set_user(reviewer)
		result = call(usage_api.reveal_patient_code, usage=usage, reason="Đối chiếu hồ sơ")
		self.assertEqual(result, {"ok": True, "usage": usage, "patient_code": "BN12345678"})
		missing = call(usage_api.reveal_patient_code, usage=usage, reason=" ")
		assert_block(self, missing, "REASON_REQUIRED", 422)
