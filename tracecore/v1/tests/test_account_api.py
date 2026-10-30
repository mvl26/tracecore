"""RPC tracecore.v1.account.* — đặt PIN trạm từ form Employee trên Desk và đổi PIN tạm tại trạm (FR-M9-09, FR-M9-09.1).

R10 đặt thẳng; R02 xác nhận bằng PIN trạm của chính mình và không tự đặt PIN cho mình. PIN mới bắt đổi ở lần quẹt thẻ kế tiếp:
nhân viên đổi ngay trên kiosk bằng `change_pin` sau khi quét thẻ.
"""

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from tracecore.core import account, station_auth
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import account as api
from tracecore.v1 import station as station_api
from tracecore.v1._common import BadRequestError

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
SUPERVISOR_PIN = "654321"
NEW_PIN = "135790"
TEMP_PIN = "112233"
CARD = "PIN-CHANGE-CARD"
CLIENT_TS = "2026-10-29T09:00:00+07:00"


class TestSetStationPin(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r10 = make_user("pin-r10@example.com", ["TC R10"])
		self.r02 = make_user("pin-r02@example.com", ["TC R02"])
		self.r04 = make_user("pin-r04@example.com", ["TC R04"])
		self.staff = make_employee(first_name="Mới vào").name
		self.supervisor = make_employee(first_name="Giám sát", user_id=self.r02).name
		station_auth.set_pin(self.supervisor, SUPERVISOR_PIN)
		for employee in (self.staff, self.supervisor):
			self.addCleanup(station_auth.clear_pin_rate_limit, employee)
		self.addCleanup(frappe.set_user, "Administrator")

	def assert_pin(self, employee, pin):
		self.assertTrue(station_auth.verify_pin(employee, pin))

	def test_r10_sets_first_pin_and_forces_change(self):
		frappe.set_user(self.r10)
		result = api.set_station_pin(self.staff, NEW_PIN)
		self.assertEqual((result["ok"], result["pin_change_required"]), (True, 1))
		self.assert_pin(self.staff, NEW_PIN)
		self.assertEqual(frappe.db.get_value("Employee", self.staff, "tc_pin_reset_required"), 1)
		events = frappe.get_all(
			"Audit Log", filters={"ref_doctype": "Employee", "ref_name": self.staff}, pluck="new_value"
		)
		self.assertTrue(any("PIN Reset" in (value or "") for value in events))
		self.assertFalse(any(NEW_PIN in (value or "") for value in events))

	def test_r02_needs_own_station_pin(self):
		frappe.set_user(self.r02)
		for pin in (None, "000000"):  # lần sai thứ 3 sẽ khóa PIN 5 phút
			result = api.set_station_pin(self.staff, NEW_PIN, supervisor_pin=pin)
			self.assertEqual((result["ok"], result["error"]["code"]), (False, "PIN_INVALID"))
		station_auth.clear_pin_rate_limit(self.supervisor)
		self.assertFalse(frappe.db.get_value("Employee", self.staff, "tc_pin_reset_required"))
		result = api.set_station_pin(self.staff, NEW_PIN, supervisor_pin=SUPERVISOR_PIN)
		self.assertTrue(result["ok"])
		self.assert_pin(self.staff, NEW_PIN)

	def test_r02_cannot_set_own_pin(self):
		frappe.set_user(self.r02)
		result = api.set_station_pin(self.supervisor, NEW_PIN, supervisor_pin=SUPERVISOR_PIN)
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "OWN_PIN_RESET"))
		self.assert_pin(self.supervisor, SUPERVISOR_PIN)

	def test_other_roles_are_refused(self):
		frappe.set_user(self.r04)
		with self.assertRaises(frappe.PermissionError):
			api.set_station_pin(self.staff, NEW_PIN, supervisor_pin=SUPERVISOR_PIN)

	def test_pin_must_be_six_digits(self):
		frappe.set_user(self.r10)
		for pin in ("12345", "1234567", "12ab56", None):
			result = api.set_station_pin(self.staff, pin)
			self.assertEqual((result["ok"], result["error"]["code"]), (False, "PIN_FORMAT_INVALID"))

	def test_form_onload_tells_whether_pin_is_set(self):
		staff = frappe.get_doc("Employee", self.staff)
		staff.run_method("onload")
		self.assertFalse(staff.get_onload().tc_has_pin)
		supervisor = frappe.get_doc("Employee", self.supervisor)
		supervisor.run_method("onload")
		self.assertTrue(supervisor.get_onload().tc_has_pin)

	def test_unknown_employee(self):
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.DoesNotExistError):
			api.set_station_pin("HR-EMP-DOES-NOT-EXIST", NEW_PIN)


class TestChangeStationPin(IsolatedTestCase):
	"""Nhân viên đổi PIN tạm ngay tại trạm sau khi quét thẻ (FR-M9-09, FR-M9-09.1, UC-33 A3).

	PIN do R10/R02 đặt trên Desk bật `tc_pin_reset_required`; phiên thẻ báo `pin_change_required` để kiosk mở modal đổi
	PIN bắt buộc, `change_pin` xác thực lại PIN cũ, tắt cờ và ghi Audit không lộ PIN.
	"""

	def setUp(self):
		super().setUp()
		self.user = make_user("pin-change@example.com", ["TC R05"])
		self.employee = make_employee(card=CARD, first_name="Đổi PIN", user_id=self.user).name
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.employee,
				"station": "TR-004",
				"valid_from": now - timedelta(hours=1),
				"valid_until": now + timedelta(hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(station_auth.clear_pin_rate_limit, self.employee)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(make_user("pin-change-r10@example.com", ["TC R10"]))
		account.reset_pin_on_desk(self.employee, TEMP_PIN)
		frappe.set_user("Administrator")
		self.token = self.login()["token"]

	def login(self):
		return station_api.login(CARD, "TR-004", client_ts=CLIENT_TS)["session"]

	def change(self, old_pin, new_pin, token=None):
		return api.change_pin(
			token=token or self.token, old_pin=old_pin, new_pin=new_pin, client_ts=CLIENT_TS
		)

	def flag(self):
		return frappe.db.get_value("Employee", self.employee, "tc_pin_reset_required")

	def test_login_and_heartbeat_report_pin_change_required(self):
		session = self.login()
		self.assertEqual(session["pin_change_required"], 1)
		self.assertEqual(
			station_api.heartbeat(session["token"], client_ts=CLIENT_TS)["pin_change_required"], 1
		)
		self.assertTrue(self.change(TEMP_PIN, NEW_PIN, session["token"])["ok"])
		self.assertEqual(
			station_api.heartbeat(session["token"], client_ts=CLIENT_TS)["pin_change_required"], 0
		)
		self.assertEqual(self.login()["pin_change_required"], 0)

	def test_change_clears_flag_and_unblocks_pin_actions(self):
		self.assertEqual(
			station_api.verify_pin(self.token, TEMP_PIN, client_ts=CLIENT_TS)["error"]["code"],
			"PIN_CHANGE_REQUIRED",
		)
		self.assertEqual(self.change(TEMP_PIN, NEW_PIN), {"ok": True, "pin_change_required": 0})
		self.assertFalse(self.flag())
		self.assertTrue(station_api.verify_pin(self.token, NEW_PIN, client_ts=CLIENT_TS)["ok"])

	def test_change_audits_event_without_secrets(self):
		self.change(TEMP_PIN, NEW_PIN)
		rows = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Employee", "ref_name": self.employee},
			fields=["user", "new_value", "station"],
		)
		changed = [row for row in rows if "PIN Changed" in (row.new_value or "")]
		self.assertEqual(len(changed), 1)
		self.assertEqual((changed[0].user, changed[0].station), (self.user, "TR-004"))
		for row in rows:
			for secret in (TEMP_PIN, NEW_PIN, self.token):
				self.assertNotIn(secret, row.new_value or "")

	def test_wrong_old_pin_is_rejected_and_keeps_temporary_pin(self):
		result = self.change("000000", NEW_PIN)
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "PIN_INVALID"))
		self.assertEqual(self.flag(), 1)
		self.assertTrue(station_auth.verify_pin(self.employee, TEMP_PIN))

	def test_new_pin_equal_to_old_pin_is_rejected(self):
		result = self.change(TEMP_PIN, TEMP_PIN)
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "PIN_REUSED"))
		self.assertEqual(self.flag(), 1)

	def test_new_pin_must_be_six_digits(self):
		for pin in ("12345", "1234567", "12ab56"):
			result = self.change(TEMP_PIN, pin)
			self.assertEqual((result["ok"], result["error"]["code"]), (False, "PIN_FORMAT_INVALID"))
		self.assertEqual(self.flag(), 1)
		self.assertTrue(station_auth.verify_pin(self.employee, TEMP_PIN))

	def test_requires_live_station_session(self):
		result = self.change(TEMP_PIN, NEW_PIN, token="not-a-session")
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "SESSION_INVALID"))
		self.assertEqual(self.flag(), 1)

	def test_pins_must_be_strings(self):
		with self.assertRaises(BadRequestError):
			self.change(None, NEW_PIN)
		with self.assertRaises(BadRequestError):
			self.change(TEMP_PIN, 135790)
