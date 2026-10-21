import importlib
import importlib.util
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.auth import LoginAttemptTracker
from frappe.utils import add_days, now_datetime, today
from frappe.utils.password import check_password, update_password

from tracecore.core import station_auth
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

test_dependencies = ["Company"]
OLD_PASSWORD = "Old-Credential-2026!"
NEW_PASSWORD = "New-Credential-2026!"


class TestAccount(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.assertIsNotNone(
			importlib.util.find_spec("tracecore.core.account"), "Task 5 account lifecycle is missing"
		)
		self.account = importlib.import_module("tracecore.core.account")
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.user = make_user("account.employee@example.test", ("TC R04",))
		self.r02 = make_user("account.supervisor@example.test", ("TC R02",))
		self.r10 = make_user("account.admin@example.test", ("TC R10",))
		update_password(self.user, OLD_PASSWORD)
		frappe.db.set_value("User", self.user, "last_password_reset_date", today())
		self.employee = self.make_employee(self.user, "ACCOUNT-CARD")
		self.supervisor = self.make_employee(self.r02, "SUPERVISOR-CARD")
		station_auth.set_pin(self.employee.name, "123456")
		station_auth.set_pin(self.supervisor.name, "654321")
		self.addCleanup(station_auth.clear_pin_rate_limit, self.employee.name)
		self.addCleanup(station_auth.clear_pin_rate_limit, self.supervisor.name)

	def make_employee(self, user, card):
		return frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": card,
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": today(),
				"company": "_Test Company",
				"status": "Active",
				"user_id": user,
				"tc_card_id": card,
				"tc_card_enabled": 1,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)

	def make_session(self, employee=None):
		employee = employee or self.employee
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": employee.name,
				"station": "TR-004",
				"valid_from": now - timedelta(hours=1),
				"valid_until": now + timedelta(hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		return station_auth.login(employee.tc_card_id, "TR-004")

	def test_password_length_and_native_update_entrypoint(self):
		with self.assertRaises(frappe.ValidationError):
			self.account.validate_password("123456789")
		self.account.validate_password("1234567890")
		with self.assertRaises(frappe.ValidationError):
			self.account.update_web_password("123456789", old_password=OLD_PASSWORD)
		self.assertEqual(
			frappe.get_hooks("override_whitelisted_methods")["frappe.core.doctype.user.user.update_password"][
				-1
			],
			"tracecore.core.account.update_web_password",
		)

	def test_password_expiry_is_at_day_90_not_day_91(self):
		frappe.db.set_value("User", self.user, "last_password_reset_date", add_days(today(), -89))
		self.assertFalse(self.account.password_is_expired(self.user))
		frappe.db.set_value("User", self.user, "last_password_reset_date", add_days(today(), -90))
		self.assertTrue(self.account.password_is_expired(self.user))
		with self.assertRaises(frappe.AuthenticationError):
			self.account.on_login(frappe._dict(user=self.user))

	def test_settings_lock_after_fifth_failure_and_two_factor_roles(self):
		from tracecore.setup.install import apply_system_settings

		apply_system_settings()
		settings = frappe.get_single("System Settings")
		self.assertEqual(settings.force_user_to_reset_password, 89)
		tracker = LoginAttemptTracker(
			"task5-account-lock",
			max_consecutive_login_attempts=settings.allow_consecutive_login_attempts,
			lock_interval=settings.allow_login_after_fail,
		)
		self.addCleanup(tracker.add_success_attempt)
		tracker.add_success_attempt()
		for _ in range(4):
			tracker.add_failure_attempt()
		self.assertTrue(tracker.is_user_allowed())
		tracker.add_failure_attempt()
		self.assertFalse(tracker.is_user_allowed())
		self.assertEqual(settings.enable_two_factor_auth, 1)
		self.assertEqual(settings.bypass_2fa_for_retricted_ip_users, 0)
		for n in range(1, 11):
			self.assertEqual(
				frappe.db.get_value("Role", f"TC R{n:02d}", "two_factor_auth"), int(n in (1, 2, 9, 10))
			)

	def test_change_password_requires_old_value_and_audits_no_secret(self):
		frappe.set_user(self.user)
		with self.assertRaises(frappe.AuthenticationError):
			self.account.change_password("incorrect-old", NEW_PASSWORD)
		self.account.change_password(OLD_PASSWORD, NEW_PASSWORD)
		self.assertEqual(check_password(self.user, NEW_PASSWORD), self.user)
		self.assertFalse(self.account.password_is_expired(self.user))
		self.assert_safe_audit(self.user, "Password Changed", OLD_PASSWORD, NEW_PASSWORD)

	def test_change_pin_requires_authenticated_session_and_old_pin(self):
		session = self.make_session()
		with self.assertRaises(Exception):
			self.account.change_pin(session["token"], "000000", "112233")
		self.account.change_pin(session["token"], "123456", "112233")
		self.assertTrue(station_auth.verify_pin(self.employee.name, "112233"))
		self.assert_safe_audit(self.employee.name, "PIN Changed", "123456", "112233")

	def test_r10_reset_forces_password_change_on_next_login(self):
		frappe.set_user(self.r10)
		self.account.reset_password(self.user, NEW_PASSWORD)
		self.assertEqual(check_password(self.user, NEW_PASSWORD), self.user)
		self.assertTrue(self.account.password_is_expired(self.user))
		self.assert_safe_audit(self.user, "Password Reset", NEW_PASSWORD)

	def test_r02_reset_requires_single_use_live_station_pin_proof(self):
		session = self.make_session(self.supervisor)
		frappe.set_user(self.r02)
		for proof in (None, self.r02, self.supervisor.name, session["token"]):
			with self.assertRaises(frappe.PermissionError):
				self.account.reset_password(self.user, NEW_PASSWORD, proof=proof)
		proof = self.account.issue_reset_proof(session["token"], "654321")
		self.account.reset_password(self.user, NEW_PASSWORD, proof=proof)
		with self.assertRaises(frappe.PermissionError):
			self.account.reset_password(self.user, OLD_PASSWORD, proof=proof)

	def test_proof_expires_and_is_bound_to_actor_and_open_session(self):
		session = self.make_session(self.supervisor)
		frappe.set_user(self.r02)
		proof = self.account.issue_reset_proof(session["token"], "654321")
		key = frappe.cache.make_key(self.account._proof_key(proof))
		self.assertGreater(frappe.cache.ttl(key), 0)
		self.assertLessEqual(frappe.cache.ttl(key), 120)
		frappe.cache.expire(key, 0)
		with self.assertRaises(frappe.PermissionError):
			self.account.reset_password(self.user, NEW_PASSWORD, proof=proof)
		proof = self.account.issue_reset_proof(session["token"], "654321")
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			self.account.reset_password(self.user, NEW_PASSWORD, proof=proof)
		frappe.set_user(self.r02)
		station_auth.logout(session["token"])
		with self.assertRaises(frappe.PermissionError):
			self.account.reset_password(self.user, NEW_PASSWORD, proof=proof)

	def test_pin_reset_requires_change_before_privileged_verification(self):
		session = self.make_session()
		frappe.set_user(self.r10)
		self.account.reset_pin(self.employee.name, "112233")
		self.assertEqual(frappe.db.get_value("Employee", self.employee.name, "tc_pin_reset_required"), 1)
		from tracecore.v1.station import verify_pin

		self.assertEqual(verify_pin(session["token"], "112233")["error"]["code"], "PIN_CHANGE_REQUIRED")
		self.account.change_pin(session["token"], "112233", "223344")
		self.assertTrue(verify_pin(session["token"], "223344")["ok"])

	def test_card_normalized_and_duplicate_rejected(self):
		self.employee.tc_card_id = "  account-normalized  "
		self.employee.save(ignore_permissions=True)
		self.assertEqual(self.employee.tc_card_id, "ACCOUNT-NORMALIZED")
		self.supervisor.tc_card_id = " account-normalized "
		with self.assertRaises(frappe.ValidationError):
			self.supervisor.save(ignore_permissions=True)

	def test_card_disable_closes_all_sessions_without_disabling_user(self):
		session = self.make_session()
		self.employee.tc_card_enabled = 0
		self.employee.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Station Session", session["session"], "is_open"), 0)
		self.assertEqual(frappe.db.get_value("User", self.user, "enabled"), 1)

	def test_leaving_disables_card_and_user_closes_sessions_and_keeps_audit(self):
		session = self.make_session()
		before = set(frappe.get_all("Audit Log", pluck="name"))
		self.employee.status = "Left"
		self.employee.relieving_date = today()
		self.employee.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Employee", self.employee.name, "tc_card_enabled"), 0)
		self.assertEqual(frappe.db.get_value("User", self.user, "enabled"), 0)
		self.assertEqual(frappe.db.get_value("Station Session", session["session"], "is_open"), 0)
		self.assertTrue(before.issubset(set(frappe.get_all("Audit Log", pluck="name"))))
		self.assertTrue(frappe.db.exists("User", self.user))
		self.assertTrue(frappe.db.exists("Employee", self.employee.name))

	def test_only_r10_can_create_disable_users_even_ignore_permissions(self):
		for actor in (self.user, self.r02):
			frappe.set_user(actor)
			with self.assertRaises(frappe.PermissionError):
				make_user("forbidden-account@example.test")
			user = frappe.get_doc("User", self.user)
			user.enabled = 0
			with self.assertRaises(frappe.PermissionError):
				user.save(ignore_permissions=True)
		frappe.set_user(self.r10)
		created = make_user("r10-created-account@example.test", ("TC R04",))
		user = frappe.get_doc("User", created)
		user.enabled = 0
		user.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("User", created, "enabled"), 0)

	def test_user_and_employee_cannot_be_deleted(self):
		for doctype, name in (("User", self.user), ("Employee", self.employee.name)):
			with self.assertRaises(frappe.ValidationError):
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

	def test_user_form_and_provision_reject_short_passwords(self):
		from tracecore.setup.provision import desk_user

		user = frappe.get_doc("User", self.user)
		user.new_password = "short"
		with self.assertRaises(frappe.ValidationError):
			user.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			desk_user("TC R10", "short-password", "short")

	def test_document_save_cannot_bypass_credential_reset_state(self):
		frappe.db.set_value("Employee", self.employee.name, "tc_pin_reset_required", 1)
		employee = frappe.get_doc("Employee", self.employee.name)
		employee.tc_pin_reset_required = 0
		with self.assertRaises(frappe.PermissionError):
			employee.save(ignore_permissions=True)

	def test_document_save_cannot_extend_password_expiry(self):
		user = frappe.get_doc("User", self.user)
		user.last_password_reset_date = add_days(today(), 365)
		with self.assertRaises(frappe.PermissionError):
			user.save(ignore_permissions=True)

	def test_pin_change_audit_uses_authenticated_station_employee(self):
		session = self.make_session()
		frappe.set_user(self.r10)
		self.account.change_pin(session["token"], "123456", "112233")
		rows = frappe.get_all(
			"Audit Log", filters={"ref_name": self.employee.name}, fields=["user", "new_value"]
		)
		changed = [row for row in rows if "PIN Changed" in (row.new_value or "")]
		self.assertEqual(changed[-1].user, self.user)

	def test_native_password_recovery_clears_forced_expiry(self):
		frappe.set_user(self.r10)
		self.account.reset_password(self.user, OLD_PASSWORD)
		frappe.set_user(self.user)
		manager = frappe._dict(
			check_password=check_password,
			login_as=lambda user: self.account.on_login(frappe._dict(user=user)),
		)
		with patch.object(frappe.local, "login_manager", manager, create=True):
			self.account.update_web_password(NEW_PASSWORD, old_password=OLD_PASSWORD)
		self.assertEqual(check_password(self.user, NEW_PASSWORD), self.user)
		self.assertFalse(self.account.password_is_expired(self.user))
		self.assertIsNone(getattr(frappe.local, "tc_password_update_user", None))

	def assert_safe_audit(self, name, event, *secrets):
		rows = frappe.get_all(
			"Audit Log", filters={"ref_name": name}, fields=["new_value", "old_value", "reason"]
		)
		serialized = frappe.as_json(rows)
		self.assertIn(event, serialized)
		for secret in secrets:
			self.assertNotIn(secret, serialized)
