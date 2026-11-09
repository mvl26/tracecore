"""Tiêm chủng nhân viên (FEAT-071; FR-M16-07, FR-M16-07.1; BRU-OCC-004; A-137 f, g)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import notification
from tracecore.occupational_safety import immunization
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

DOCTYPE = "Staff Immunization"


def dose(employee, vaccine, dose_no, given_on):
	return frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"employee": employee,
			"vaccine": vaccine,
			"dose_no": dose_no,
			"given_on": given_on,
		}
	).insert(ignore_permissions=True)


class TestStaffImmunization(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		for name in frappe.get_all("Immunization Requirement", pluck="name"):
			frappe.db.set_value("Immunization Requirement", name, "status", "Draft")
		self.icu = factories.make_department("PN Hồi sức")
		self.ward = factories.make_department("PN Nội")
		self.user = factories.make_user("os-imm-staff@example.com", roles=["TC R08"])
		self.r02 = factories.make_user("os-imm-r02@example.com", roles=["TC R02"])
		self.nurse = fx.employee("PN Imm Nurse", self.icu, user=self.user)
		self.req = fx.requirement("PN Test HepB", doses=3, interval=30, booster=0, departments=[self.icu])

	def test_next_due_between_doses_and_none_after_last(self):
		first = dose(self.nurse, self.req.name, 1, add_days(today(), -10))
		self.assertEqual(getdate(first.next_due), getdate(add_days(today(), 20)))
		last = dose(self.nurse, self.req.name, 3, today())
		self.assertIsNone(last.next_due)

	def test_booster_after_full_course(self):
		req = fx.requirement("PN Test Flu", doses=1, interval=0, booster=365, departments=[self.icu])
		row = dose(self.nurse, req.name, 1, today())
		self.assertEqual(getdate(row.next_due), getdate(add_days(today(), 365)))

	def test_future_date_and_zero_dose_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			dose(self.nurse, self.req.name, 1, add_days(today(), 1))
		with self.assertRaises(frappe.ValidationError):
			dose(self.nurse, self.req.name, 0, today())

	def test_reminds_staff_and_r02_once_per_level(self):
		"""FR-M16-07: nhắc theo mức 60/30/7/quá hạn như FR-M4-01.4, mỗi mức một lần."""
		row = dose(self.nurse, self.req.name, 1, add_days(today(), -25))  # hạn còn 5 ngày → mức 7
		self.assertEqual(immunization.remind_due(), 1)
		self.assertEqual(immunization.remind_due(), 0)
		for user in (self.user, self.r02):
			self.assertTrue(
				frappe.db.exists(
					"Notification Delivery",
					{"event_code": "IMMUNIZATION_DUE", "recipient": user, "ref_name": row.name},
				),
				user,
			)
		self.assertEqual(immunization.remind_due(add_days(today(), 6)), 1)  # quá hạn → nhắc mức cuối

	def test_only_latest_dose_is_reminded(self):
		dose(self.nurse, self.req.name, 1, add_days(today(), -25))
		dose(self.nurse, self.req.name, 3, today())
		self.assertEqual(immunization.remind_due(), 0)

	def test_coverage_excludes_left_staff_and_other_departments(self):
		"""FR-M16-07.1: nhân viên nghỉ việc không vào mẫu số."""
		full = fx.employee("PN Imm Full", self.icu)
		fx.employee("PN Imm Missing", self.icu)
		left = fx.employee("PN Imm Left", self.icu)
		frappe.db.set_value("Employee", left, {"status": "Left", "relieving_date": today()})
		fx.employee("PN Imm Ward", self.ward)
		dose(full, self.req.name, 3, today())
		result = immunization.coverage(department=self.icu)
		row = next(v for v in result["vaccines"] if v["vaccine"] == self.req.name)
		self.assertEqual((row["covered"], row["at_risk"]), (1, 3))  # nurse, full, missing
		self.assertEqual(result["rate"], round(100 / 3, 1))

	def test_designation_scope(self):
		tech = fx.employee("PN Imm Tech", self.ward, designation="PN Lab Tech")
		req = fx.requirement("PN Test Desig", doses=1, designations=["PN Lab Tech"])
		dose(tech, req.name, 1, today())
		row = next(v for v in immunization.coverage()["vaccines"] if v["vaccine"] == req.name)
		self.assertEqual((row["covered"], row["at_risk"]), (1, 1))

	def test_draft_requirement_not_counted(self):
		fx.requirement("PN Test Draft", doses=1, departments=[self.icu], approve=False)
		names = [v["vaccine"] for v in immunization.coverage()["vaccines"]]
		self.assertNotIn("PN Test Draft", names)
