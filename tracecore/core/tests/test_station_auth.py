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


def setup_operator(case):
	"""Người giữ phiên NV-AUTH-001 (R04, PIN 123456) có năng lực tại TR-004."""
	case.user = make_user("station.operator@example.test", ("TC R04",))
	case.employee = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "Station",
			"last_name": "Operator",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": today(),
			"company": "_Test Company",
			"status": "Active",
			"user_id": case.user,
			"tc_card_id": "NV-AUTH-001",
			"tc_card_enabled": 1,
		}
	).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
	start = now_datetime()
	case.competency = frappe.get_doc(
		{
			"doctype": "Station Competency",
			"employee": case.employee.name,
			"station": "TR-004",
			"valid_from": add_to_date(start, hours=-1),
			"valid_until": add_to_date(start, hours=8),
			"is_active": 1,
		}
	).insert(ignore_permissions=True)
	station_auth.set_pin(case.employee.name, "123456")
	station_auth.clear_pin_rate_limit(case.employee.name)


class TestStationAuth(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		setup_operator(self)

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


class TestApproverProof(IsolatedTestCase):
	"""R02 quét thẻ + PIN trên kiosk của người khác (architecture C6, UC-12 A1): proof dùng một lần gắn với phiên đó."""

	def setUp(self):
		super().setUp()
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		setup_operator(self)

	def make_approver(self, card="NV-R02-001", roles=("TC R02",), pin="654321"):
		user = make_user(card.lower() + "@example.test", roles)
		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Giám sát",
				"last_name": card,
				"gender": "Female",
				"date_of_birth": "1990-01-01",
				"date_of_joining": today(),
				"company": "_Test Company",
				"status": "Active",
				"user_id": user,
				"tc_card_id": card,
				"tc_card_enabled": 1,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
		station_auth.set_pin(employee.name, pin)
		station_auth.clear_pin_rate_limit(employee.name)
		return employee

	def assert_block(self, code, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		self.assertEqual(caught.exception.block.code, code)

	@bru("BRU-PAR-005")
	def test_proof_is_one_time_and_bound_to_operator_session(self):
		approver = self.make_approver()
		login = station_auth.login("NV-AUTH-001", "TR-004")
		result = station_auth.create_approver_proof(login["token"], " nv-r02-001 ", "654321")
		self.assertTrue(result["proof"])
		self.assertEqual(result["expires_in"], station_auth.PROOF_SECONDS)
		self.assertEqual(result["employee_name"], approver.employee_name)

		got = station_auth.consume_approver_proof(login["session"], result["proof"])
		self.assertEqual((got.employee, got.user), (approver.name, approver.user_id))
		# dùng một lần
		self.assert_block(
			"PIN_PROOF_INVALID", station_auth.consume_approver_proof, login["session"], result["proof"]
		)
		# phiên khác, hoặc role khác role đã duyệt → không nhận
		other = station_auth.create_approver_proof(login["token"], "NV-R02-001", "654321")["proof"]
		self.assert_block("PIN_PROOF_INVALID", station_auth.consume_approver_proof, "SES-OTHER", other)
		other = station_auth.create_approver_proof(login["token"], "NV-R02-001", "654321")["proof"]
		self.assert_block(
			"PIN_PROOF_INVALID", station_auth.consume_approver_proof, login["session"], other, role="TC R01"
		)
		# proof không phải proof duyệt (PIN của chính người giữ phiên) → không nhận
		own = station_auth.create_pin_proof(login["token"], "123456")["proof"]
		self.assert_block("PIN_PROOF_INVALID", station_auth.consume_approver_proof, login["session"], own)

	@bru("BRU-PAR-005")
	def test_proof_rejected_after_logout_or_approver_loses_role(self):
		approver = self.make_approver()
		login = station_auth.login("NV-AUTH-001", "TR-004")
		proof = station_auth.create_approver_proof(login["token"], "NV-R02-001", "654321")["proof"]
		frappe.get_doc("User", approver.user_id).remove_roles("TC R02")
		self.assert_block(
			"APPROVER_NOT_ALLOWED", station_auth.consume_approver_proof, login["session"], proof
		)

		frappe.get_doc("User", approver.user_id).add_roles("TC R02")
		proof = station_auth.create_approver_proof(login["token"], "NV-R02-001", "654321")["proof"]
		station_auth.logout(login["token"])
		self.assert_block("PIN_PROOF_INVALID", station_auth.consume_approver_proof, login["session"], proof)

	def test_create_rejects_wrong_pin_card_role_and_session(self):
		self.make_approver()
		self.make_approver(card="NV-R06-009", roles=("TC R06",))
		token = station_auth.login("NV-AUTH-001", "TR-004")["token"]
		self.assert_block("PIN_INVALID", station_auth.create_approver_proof, token, "NV-R02-001", "000000")
		self.assert_block("CARD_INVALID", station_auth.create_approver_proof, token, "NV-KHONG-CO", "654321")
		# người không có role duyệt: chặn trước khi thử PIN (không đốt lượt PIN)
		self.assert_block(
			"APPROVER_NOT_ALLOWED", station_auth.create_approver_proof, token, "NV-R06-009", "654321"
		)
		# role xin duyệt phải là role được ủy quyền duyệt
		self.assert_block(
			"APPROVER_NOT_ALLOWED",
			station_auth.create_approver_proof,
			token,
			"NV-R02-001",
			"654321",
			role="TC R06",
		)
		self.assert_block(
			"SESSION_INVALID", station_auth.create_approver_proof, "sai", "NV-R02-001", "654321"
		)

	def test_create_requires_changed_pin(self):
		approver = self.make_approver()
		frappe.db.set_value("Employee", approver.name, "tc_pin_reset_required", 1)
		token = station_auth.login("NV-AUTH-001", "TR-004")["token"]
		self.assert_block(
			"PIN_CHANGE_REQUIRED", station_auth.create_approver_proof, token, "NV-R02-001", "654321"
		)

	def test_v1_verify_approver_returns_proof_or_stable_error(self):
		self.make_approver()
		ts = "2026-10-26T09:00:00+07:00"
		token = station_api.login(card_id="NV-AUTH-001", station="TR-004", client_ts=ts)["session"]["token"]
		ok = station_api.verify_approver(
			token=token, card_id="NV-R02-001", pin="654321", role="TC R02", client_ts=ts
		)
		self.assertTrue(ok["ok"])
		self.assertTrue(ok["proof"])
		wrong = station_api.verify_approver(token=token, card_id="NV-R02-001", pin="000000", client_ts=ts)
		self.assertFalse(wrong["ok"])
		self.assertEqual(wrong["error"]["code"], "PIN_INVALID")
