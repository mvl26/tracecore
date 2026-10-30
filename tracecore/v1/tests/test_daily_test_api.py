"""RPC tracecore.v1.daily_test.* (FEAT-040): ghi test, khóa máy, mở khóa tạm chỉ R02; mã HTTP, quyền, idempotent."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_days, today

from tracecore.reprocessing import sterilizing
from tracecore.tests.factories import make_sterilizer, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import daily_test as api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-005"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
SESSION_TOKENS = {}


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("token", SESSION_TOKENS.get(frappe.session.user))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": STATION}):
		return fn(**kwargs)


class TestDailyTestApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		SESSION_TOKENS.clear()
		self.addCleanup(SESSION_TOKENS.clear)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		frappe.set_user("Administrator")
		self.machine = make_sterilizer(daily_tested=False)
		self.technician = self.as_user("ktv-tiet-khuan@example.com", ["TC R05"])

	def as_user(self, email, roles):
		frappe.set_user("Administrator")
		user = make_user(email, roles=roles)
		SESSION_TOKENS[user] = make_station_session(user, STATION)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		return user

	def args_for(self, **extra):
		return {
			"equipment": self.machine.name,
			"lot": "BD-001",
			"lot_expiry": add_days(today(), 30),
			"station": STATION,
			**extra,
		}

	@bru("BRU-EQP-001")
	def test_record_both_tests_opens_the_machine_for_loading(self):
		self.assertEqual(sterilizing.check_equipment_ready(self.machine.name).code, "DAILY_TEST_REQUIRED")
		listing = call(api.overview, station=STATION)
		self.assertEqual(
			[row["missing"] for row in listing["equipment"] if row["name"] == self.machine.name],
			[["bowie_dick", "leak"]],
		)
		for test_type in ("bowie_dick", "leak"):
			done = call(
				api.record, test_type=test_type, result="Pass", photo="/files/x.png", **self.args_for()
			)
			self.assertTrue(done["ok"])
		self.assertIsNone(sterilizing.check_equipment_ready(self.machine.name))

	def test_record_rejects_expired_lot_with_http_422(self):
		bad = call(
			api.record, test_type="leak", result="Pass", **self.args_for(lot_expiry=add_days(today(), -1))
		)
		self.assertEqual(bad["error"]["code"], "TEST_LOT_EXPIRED")
		self.assertEqual(frappe.local.response.get("http_status_code"), 422)

	def test_replay_with_same_key_records_one_test(self):
		key, stamp = str(uuid.uuid4()), now_ts()
		args = self.args_for(test_type="leak", result="Pass", client_ts=stamp)
		first = call(api.record, key, **args)
		again = call(api.record, key, **args)
		self.assertEqual(first["daily_test"], again["daily_test"])
		self.assertEqual(frappe.db.count("Daily Test", {"equipment": self.machine.name}), 1)

	@bru("BRU-EQP-002")
	def test_only_r02_unlocks_temporarily(self):
		with self.assertRaises(frappe.PermissionError):
			call(api.unlock_temp, equipment=self.machine.name, reason="Ca khẩn", hours=2, station=STATION)
		self.assertEqual(frappe.db.get_value("Equipment", self.machine.name, "unlock_until"), None)
		self.as_user("giam-sat-kt@example.com", ["TC R02"])
		done = call(api.unlock_temp, equipment=self.machine.name, reason="Ca khẩn", hours=2, station=STATION)
		self.assertTrue(done["ok"])
		self.assertIsNone(sterilizing.check_equipment_ready(self.machine.name))
		bad = call(api.unlock_temp, equipment=self.machine.name, reason="Ca khẩn", hours=48, station=STATION)
		self.assertEqual(bad["error"]["code"], "UNLOCK_INVALID")

	def test_other_roles_cannot_record(self):
		self.as_user("kho-kt@example.com", ["TC R06"])
		with self.assertRaises(frappe.PermissionError):
			call(api.overview, station=STATION)
