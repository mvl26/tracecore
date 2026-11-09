"""Print Format "Kế hoạch KSNK năm", "Báo cáo tổng kết KSNK" và Script Report "Tổng kết KSNK năm" (FEAT-058 AC-6, AC-7;
FR-M11-04, FR-M11-06, FR-M11-06.2)."""

import frappe
from frappe.utils import today

from tracecore.infection_program import plan_print
from tracecore.infection_program.report.ic_annual_summary import ic_annual_summary
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests.utils import IsolatedTestCase

YEAR = 2092


class TestICPlanPrint(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_plans(YEAR)
		self.ind = fx.indicator("T-PRINT-HH")
		fx.indicator_value(self.ind, f"{YEAR}-01", 784, 1000, locked=0)
		owner = fx.employee("Print Owner")
		self.plan = fx.plan(
			YEAR,
			indicators=[(self.ind, 71, 80)],
			activities=[
				{
					"activity": "Hand rub <b>",
					"responsible": owner,
					"due_date": today(),
					"budget_vnd": 486000000,
				}
			],
		)

	def test_formats_registered(self):
		for name in ("TC IC Annual Plan", "TC IC Annual Summary"):
			fmt = frappe.get_doc("Print Format", name)
			self.assertEqual(
				(fmt.doc_type, fmt.standard, fmt.module), ("IC Annual Plan", "Yes", "Infection Program")
			)

	def test_context_formats_vietnamese_numbers(self):
		cs = plan_print.tc_ic_plan_context(self.plan.name)
		self.assertTrue(cs["draft"])
		self.assertTrue(cs["provisional"])
		self.assertEqual(cs["total_budget"], "486.000.000")
		self.assertEqual(cs["indicators"][0]["target"], "≥ 80 %")
		self.assertEqual(cs["indicators"][0]["value"], "78,4 %")
		self.assertRegex(cs["activities"][0]["due_date"], r"^\d{2}/\d{2}/\d{4}$")
		self.assertEqual(plan_print.number(1234.56), "1.234,6")
		self.assertEqual(plan_print.number(None), "")

	def test_rendered_plan_and_summary(self):
		plan_html = frappe.get_print("IC Annual Plan", self.plan.name, "TC IC Annual Plan")
		self.assertIn("Annual infection control plan 2092", plan_html)
		self.assertIn("Draft, not approved yet", plan_html)
		self.assertIn("Hand rub &lt;b&gt;", plan_html)
		summary_html = frappe.get_print("IC Annual Plan", self.plan.name, "TC IC Annual Summary")
		self.assertIn("Provisional", summary_html)
		self.assertIn("78,4 %", summary_html)
		self.assertIn("0/1 completed", summary_html)

	def test_print_needs_read_permission(self):
		r02 = fx.user("R02", prefix="print")
		frappe.set_user(r02)
		with self.assertRaises(frappe.PermissionError):
			plan_print.tc_ic_plan_context(self.plan.name)

	def test_summary_report_rows_and_message(self):
		columns, data, message = ic_annual_summary.execute({"plan": self.plan.name})
		self.assertEqual([c["fieldname"] for c in columns][-2:], ["value", "status"])
		self.assertAlmostEqual(data[0]["value"], 78.4)
		self.assertEqual(data[0]["status"], "Not met")
		self.assertIn("0/1", message)
		self.assertIn("Provisional", message)
		self.assertEqual(ic_annual_summary.execute({})[1], [])
