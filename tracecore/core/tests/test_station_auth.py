from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime, today

from tracecore.core import station_auth
from tracecore.core.errors import BlockedError
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import station as station_api

test_dependencies = ["Company"]


class TestStationAuth(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		self.user = make_user("station.operator@example.test", ("TC R04",))
		self.employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Station",
				"last_name": "Operator",
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": today(),
				"company": "_Test Company",
				"status": "Active",
				"user_id": self.user,
				"tc_card_id": "NV-AUTH-001",
				"tc_card_enabled": 1,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
		start = now_datetime()
		self.competency = frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.employee.name,
				"station": "TR-004",
				"valid_from": add_to_date(start, hours=-1),
				"valid_until": add_to_date(start, hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		station_auth.set_pin(self.employee.name, "123456")
		station_auth.clear_pin_rate_limit(self.employee.name)

	@bru("BRU-HR-001")
	def test_login_requires_active_competency_and_returns_one_time_token(self):
		result = station_auth.login(" nv-auth-001 ", "TR-004")
		self.assertTrue(result["token"])
		self.assertEqual(result["employee"], self.employee.name)
		session = frappe.get_doc("Station Session", result["session"])
		self.assertNotEqual(session.token_hash, result["token"])
		self.assertEqual(session.station, "TR-004")
		self.assertEqual(session.is_open, 1)

		self.competency.is_active = 0
		self.competency.save(ignore_permissions=True)
		with self.assertRaises(BlockedError) as caught:
			station_auth.login("NV-AUTH-001", "TR-004")
		# Public code and text must not reveal that the card itself exists; the audit keeps the cause.
		self.assertEqual(caught.exception.block.code, "CARD_INVALID")
		with self.assertRaises(BlockedError) as unknown:
			station_auth.login("NV-NO-SUCH-CARD", "TR-004")
		self.assertEqual(unknown.exception.block.as_dict(), caught.exception.block.as_dict())
		reasons = frappe.get_all(
			"Audit Log", filters={"ref_name": self.employee.name, "action": "Reject"}, pluck="new_value"
		)
		self.assertTrue(any("COMPETENCY_REQUIRED" in (value or "") for value in reasons))

	def test_rejected_card_scans_are_throttled_per_client(self):
		self.addCleanup(station_auth.clear_login_throttle)
		station_auth.clear_login_throttle()
		with patch.object(station_auth, "LOGIN_FAILURE_LIMIT", 3):
			for _ in range(3):
				with self.assertRaises(BlockedError) as caught:
					station_auth.login("NV-NO-SUCH-CARD", "TR-004")
				self.assertEqual(caught.exception.block.code, "CARD_INVALID")
			with self.assertRaises(BlockedError) as throttled:
				station_auth.login("NV-AUTH-001", "TR-004")
		self.assertEqual(throttled.exception.block.code, "LOGIN_THROTTLED")
		self.assertEqual(throttled.exception.block.http_status, 429)

	def test_second_login_closes_previous_session(self):
		first = station_auth.login("NV-AUTH-001", "TR-004")
		second = station_auth.login("NV-AUTH-001", "TR-004")
		self.assertNotEqual(first["session"], second["session"])
		old = frappe.get_doc("Station Session", first["session"])
		self.assertEqual(old.is_open, 0)
		self.assertEqual(old.end_reason, "Replaced")
		self.assertEqual(
			frappe.db.count("Station Session", {"employee": self.employee.name, "is_open": 1}), 1
		)

	def test_absolute_and_idle_expiry_are_enforced_server_side(self):
		result = station_auth.login("NV-AUTH-001", "TR-004")
		frappe.db.set_value(
			"Station Session", result["session"], "absolute_expires_at", now_datetime() - timedelta(seconds=1)
		)
		with self.assertRaises(BlockedError) as caught:
			station_auth.authenticate_session(result["token"])
		self.assertEqual(caught.exception.block.code, "SESSION_EXPIRED")

		result = station_auth.login("NV-AUTH-001", "TR-004")
		frappe.db.set_value(
			"Station Session", result["session"], "last_activity_at", now_datetime() - timedelta(minutes=11)
		)
		with self.assertRaises(BlockedError) as caught:
			station_auth.authenticate_session(result["token"])
		self.assertEqual(caught.exception.block.code, "SESSION_IDLE")

	def test_pin_is_bcrypt_and_three_failures_lock_for_five_minutes(self):
		stored = frappe.utils.password.get_decrypted_password(
			"Employee", self.employee.name, "tc_pin_hash", raise_exception=False
		)
		self.assertTrue(stored.startswith("$2"))
		for attempt in range(3):
			with self.assertRaises(BlockedError) as caught:
				station_auth.verify_pin(self.employee.name, "000000")
			expected = "PIN_LOCKED" if attempt == 2 else "PIN_INVALID"
			self.assertEqual(caught.exception.block.code, expected)
		with self.assertRaises(BlockedError) as caught:
			station_auth.verify_pin(self.employee.name, "123456")
		self.assertEqual(caught.exception.block.code, "PIN_LOCKED")

	def test_pin_failure_counter_is_atomic_not_read_modify_write(self):
		# Parallel guesses can all read a stale counter; the limit must use an atomic increment.
		original = type(frappe.cache).get_value

		def stale(cache, key, *args, **kwargs):
			if str(key).startswith("tracecore:pin"):
				return 0
			return original(cache, key, *args, **kwargs)

		with patch.object(type(frappe.cache), "get_value", stale):
			codes = []
			for _ in range(3):
				with self.assertRaises(BlockedError) as caught:
					station_auth.verify_pin(self.employee.name, "000000")
				codes.append(caught.exception.block.code)
		self.assertEqual(codes, ["PIN_INVALID", "PIN_INVALID", "PIN_LOCKED"])

	def test_logout_and_heartbeat_require_the_token(self):
		result = station_auth.login("NV-AUTH-001", "TR-004")
		session = station_auth.heartbeat(result["token"])
		self.assertEqual(session.name, result["session"])
		station_auth.logout(result["token"])
		with self.assertRaises(BlockedError) as caught:
			station_auth.heartbeat(result["token"])
		self.assertEqual(caught.exception.block.code, "SESSION_INVALID")

	def test_v1_station_session_endpoints_return_stable_bodies(self):
		ts = "2026-10-21T09:00:00+07:00"
		login = station_api.login(card_id="NV-AUTH-001", station="TR-004", client_ts=ts)
		self.assertTrue(login["ok"])
		self.assertTrue(login["session"]["token"])
		heartbeat = station_api.heartbeat(token=login["session"]["token"], client_ts=ts)
		self.assertEqual(heartbeat["session"], login["session"]["session"])
		verified = station_api.verify_pin(token=login["session"]["token"], pin="123456", client_ts=ts)
		self.assertTrue(verified["proof"])
		self.assertTrue(station_api.logout(token=login["session"]["token"], client_ts=ts)["ok"])
		failed = station_api.heartbeat(token=login["session"]["token"], client_ts=ts)
		self.assertFalse(failed["ok"])
		self.assertEqual(failed["error"]["code"], "SESSION_INVALID")
