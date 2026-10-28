"""RPC tracecore.v1.account.set_station_pin — đặt PIN trạm cho nhân viên từ form Employee trên Desk (FR-M9-09.1).

R10 đặt thẳng; R02 xác nhận bằng PIN trạm của chính mình và không tự đặt PIN cho mình. PIN mới bắt đổi ở lần quẹt thẻ kế tiếp.
"""

import frappe

from tracecore.core import station_auth
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import account as api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
SUPERVISOR_PIN = "654321"
NEW_PIN = "135790"


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
