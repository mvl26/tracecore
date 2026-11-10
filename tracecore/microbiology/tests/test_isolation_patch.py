"""Patch A-146 Q1: cờ khoa lâm sàng điền sẵn từ khoa nội trú (FEAT-068; FR-M14-07.1)."""

import frappe

from tracecore.patches.v0_1 import a146_department_clinical
from tracecore.tests.factories import make_department
from tracecore.tests.utils import IsolatedTestCase


class TestDepartmentClinicalPatch(IsolatedTestCase):
	def test_inpatient_wards_become_clinical_and_rerun_keeps_edits(self):
		ward = make_department("CL Patch Nội trú")
		office = make_department("CL Patch Hành chính")
		frappe.db.set_value("Department", ward, {"tc_inpatient": 1, "tc_clinical": 0})
		frappe.db.set_value("Department", office, {"tc_inpatient": 0, "tc_clinical": 0})
		a146_department_clinical.execute()
		self.assertEqual(frappe.db.get_value("Department", ward, "tc_clinical"), 1)
		self.assertEqual(frappe.db.get_value("Department", office, "tc_clinical"), 0)
		frappe.db.set_value("Department", office, "tc_clinical", 1)
		a146_department_clinical.execute()
		self.assertEqual(frappe.db.get_value("Department", office, "tc_clinical"), 1)
		self.assertTrue(frappe.db.exists("Custom Field", a146_department_clinical.FIELD))
