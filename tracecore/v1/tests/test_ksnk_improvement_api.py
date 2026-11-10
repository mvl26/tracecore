"""RPC tracecore.v1.ksnk_improvement.status — khối cải tiến chất lượng và tự đánh giá của SCR-49 (FEAT-072 AC-1, AC-6,
AC-12; FR-M11-12, FR-M11-13.1; UC-42; A-149)."""

import frappe
from frappe.utils import getdate, today

from tracecore.infection_program import improvement
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import ksnk_improvement

YEAR = getdate(today()).year


class TestKsnkImprovementApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.lang = "en"
		frappe.db.delete(improvement.DOCTYPE)
		frappe.get_doc(
			{
				"doctype": improvement.DOCTYPE,
				"project_type": "Quality Improvement",
				"title": "Giảm CAUTI",
				"start_date": f"{YEAR}-01-02",
				"end_date": f"{YEAR}-01-10",
				"status": improvement.COMPLETED,
				"result_summary": "4,2 → 2,0 ‰",
			}
		).insert(ignore_permissions=True)

	def test_r01_sees_projects_and_can_edit(self):
		frappe.set_user(factories.make_user("api072i-r01@test.local", ["TC R01"]))
		data = ksnk_improvement.status(YEAR)
		self.assertEqual(data["year"], YEAR)
		self.assertTrue(data["can_edit"])
		self.assertEqual(data["improvement"]["completed"], 1)
		self.assertEqual(data["improvement"]["projects"][0]["status_label"], "Completed")
		self.assertIn("current", data["self_assessment"])

	def test_r13_reads_without_edit(self):
		frappe.set_user(factories.make_user("api072i-r13@test.local", ["TC R13"]))
		data = ksnk_improvement.status()
		self.assertFalse(data["can_edit"])
		self.assertEqual(data["improvement"]["total"], 1)

	def test_r12_cannot_open(self):
		frappe.set_user(factories.make_user("api072i-r12@test.local", ["TC R12"]))
		with self.assertRaises(frappe.PermissionError):
			ksnk_improvement.status()

	def test_invalid_year_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			ksnk_improvement.status("abc")
