"""Quyền xem hồ sơ phơi nhiễm và mã BN nguồn (FEAT-071; FR-M16-05, 05.1, 05.2; BRU-OCC-003; NFR-PRIV-01; NFR-SEC-09;
ADR-010; UC-55 A4, E1, E2; F-22)."""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.occupational_safety import exposure, patient_code
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

DOCTYPE = "Occupational Exposure"
M16 = (
	"Occupational Exposure",
	"Exposure Follow-up Template",
	"Immunization Requirement",
	"Staff Immunization",
)


class TestExposurePrivacy(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.department = factories.make_department("PN Cấp cứu")
		self.staff_user = factories.make_user("os-priv-staff@example.com", roles=["TC R08"])
		self.staff = fx.employee("PN Priv Staff", self.department, user=self.staff_user)
		self.other = fx.employee("PN Priv Other", self.department)
		self.users = {
			role: factories.make_user(f"os-priv-{role[-3:].lower()}@example.com", roles=[role])
			for role in ("TC R01", "TC R02", "TC R08", "TC R11", "TC R12", "TC R13")
		}
		self.doc = exposure.create_report(
			{
				"employee": self.staff,
				"exposure_type": fx.SPLASH,
				"occurred_at": fx.hours_ago(2),
				"source_known": "Yes",
				"source_patient_code": "BN0099887766",
			},
			channel="Department Portal",
		)
		self.other_doc = exposure.create_report(
			{"employee": self.other, "exposure_type": fx.SHARPS, "occurred_at": fx.hours_ago(1)},
			channel="PDA",
		)

	def test_permission_matrix(self):
		for doctype in M16:
			assert_permission_matrix(self, doctype)

	@bru("BRU-OCC-003")
	def test_only_r01_and_r11_read_exposure_records(self):
		for role, user in self.users.items():
			allowed = role in ("TC R01", "TC R11")
			self.assertEqual(frappe.has_permission(DOCTYPE, "read", self.doc, user=user), allowed, role)
			frappe.set_user(user)
			if allowed:
				self.assertIn(self.doc.name, frappe.get_list(DOCTYPE, pluck="name"))
			else:
				try:
					names = frappe.get_list(DOCTYPE, pluck="name")
				except frappe.PermissionError:
					names = []
				self.assertEqual(names, [], role)
			frappe.set_user("Administrator")

	def test_staff_sees_only_own_records_without_patient_code(self):
		"""UC-55 A4: nhân viên xem hồ sơ của mình (không qua DocPerm), không thấy mã BN nguồn."""
		frappe.set_user(self.staff_user)
		rows = exposure.my_records()
		self.assertEqual([row.name for row in rows], [self.doc.name])
		self.assertNotIn("source_patient_code_masked", rows[0])
		self.assertNotIn("BN0099887766", frappe.as_json(rows))
		self.assertFalse(frappe.has_permission(DOCTYPE, "read", self.doc, user=self.staff_user))

	def test_reveal_requires_r01_r11_and_reason(self):
		frappe.set_user(self.users["TC R02"])
		with self.assertRaises(frappe.PermissionError):
			patient_code.reveal(DOCTYPE, self.doc.name, "check")
		frappe.set_user(self.users["TC R11"])
		with self.assertRaises(BlockedError):
			patient_code.reveal(DOCTYPE, self.doc.name, " ")
		self.assertEqual(patient_code.reveal(DOCTYPE, self.doc.name, "Source testing"), "BN0099887766")
		frappe.set_user("Administrator")
		logs = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": DOCTYPE, "ref_name": self.doc.name, "action": "View Patient Code"},
			fields=["reason", "old_value", "new_value"],
		)
		self.assertEqual(len(logs), 1)
		self.assertNotIn("BN0099887766", frappe.as_json(logs))

	def test_badge_counts_new_records_for_managers_only(self):
		self.assertEqual(exposure.badges(self.users["TC R02"]), {})
		count = exposure.badges(self.users["TC R11"])["phoi-nhiem"]
		self.assertGreaterEqual(count, 2)
