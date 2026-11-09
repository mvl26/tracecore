"""IC Annual Plan — kế hoạch KSNK năm (FEAT-058 AC-1..AC-4, AC-6; FR-M11-04..06; BRU-ICP-004; UC-41 A1, A2, E1–E3)."""

import frappe
from frappe.utils import add_days, today

from tracecore.infection_program import annual_plan
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

DOCTYPE = "IC Annual Plan"
YEAR = 2091


class TestICAnnualPlan(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_plans(YEAR)
		self.r01 = fx.user("R01")
		self.r13 = fx.user("R13")
		self.owner_emp = fx.employee("Plan Owner", user=fx.user("R11", prefix="plan-owner"))
		self.ind = fx.indicator("T-PLAN-HH")

	def _plan(self, **kw):
		return fx.plan(
			kw.pop("year", YEAR),
			indicators=[(self.ind, 71, 80)],
			activities=[{"activity": "VST training", "responsible": self.owner_emp, "due_date": today()}],
			**kw,
		)

	def test_meta_and_permissions(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertTrue(meta.is_submittable)
		self.assertEqual(meta.module, "Infection Program")
		activity = frappe.get_meta("IC Plan Activity")
		self.assertTrue(activity.get_field("status").allow_on_submit)
		self.assertTrue(activity.get_field("evidence").allow_on_submit)
		self.assertFalse(activity.get_field("due_date").allow_on_submit)
		self.assertIsNone(activity.get_field("owner"))  # A-133 a: `responsible`, không đè trường hệ thống
		self.assertTrue(meta.get_field("summary").allow_on_submit)
		assert_permission_matrix(self, DOCTYPE)

	def test_name_uses_plan_year_and_totals_budget(self):
		doc = self._plan()
		self.assertTrue(doc.name.startswith(f"KH-{YEAR}-"))
		self.assertEqual(doc.total_budget_vnd, 1000000)

	@bru("BRU-ICP-004")
	def test_r01_cannot_approve(self):
		doc = self._plan()
		frappe.set_user(self.r01)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(DOCTYPE, doc.name).submit()
		with self.assertRaises(frappe.PermissionError):
			annual_plan.approve(doc.name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 0)

	@bru("BRU-ICP-004")
	def test_r13_approves_and_is_recorded(self):
		doc = fx.approve(self._plan(), self.r13)
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.approved_by, self.r13)
		self.assertTrue(doc.approved_on)

	@bru("BRU-ICP-004")
	def test_second_plan_same_year_blocked(self):
		first = fx.approve(self._plan(), self.r13)
		with self.assertRaises(frappe.ValidationError) as caught:
			self._plan()
		self.assertIn(first.name, str(caught.exception))

	@bru("BRU-ICP-004")
	def test_approved_content_locked_progress_open(self):
		doc = fx.approve(self._plan(), self.r13)
		doc.reload()
		doc.activities[0].due_date = add_days(today(), 30)
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.save()
		self.assertIn("Amend", str(caught.exception))
		doc.reload()
		doc.objectives = "Changed"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.activities[0].status = "Completed"
		doc.activities[0].evidence = "389 cases"
		doc.summary = "Good year"
		doc.save()
		doc.reload()
		self.assertEqual(doc.activities[0].status, "Completed")
		self.assertTrue(doc.activities[0].completed_on)

	@bru("BRU-ICP-004")
	def test_amendment_keeps_original_until_approved(self):
		original = fx.approve(self._plan(), self.r13)
		frappe.set_user(self.r01)
		name = annual_plan.make_amendment(original.name)
		self.assertEqual(annual_plan.make_amendment(original.name), name)  # không tạo bản Nháp thứ hai
		frappe.set_user("Administrator")
		amendment = frappe.get_doc(DOCTYPE, name)
		self.assertEqual(amendment.amended_from, original.name)
		self.assertEqual(amendment.docstatus, 0)
		self.assertFalse(amendment.approved_by)
		self.assertEqual(frappe.db.get_value(DOCTYPE, original.name, "docstatus"), 1)
		amendment.activities[0].due_date = add_days(today(), 60)
		amendment.save()
		fx.approve(amendment, self.r13)
		self.assertEqual(frappe.db.get_value(DOCTYPE, original.name, "docstatus"), 2)
		self.assertEqual(
			frappe.db.count(DOCTYPE, {"year": YEAR, "docstatus": 1}), 1
		)  # luôn tối đa một bản hiệu lực

	def test_amendment_must_keep_year(self):
		original = fx.approve(self._plan(), self.r13)
		copy = frappe.copy_doc(original)
		copy.amended_from = original.name
		copy.year = YEAR + 1
		with self.assertRaises(frappe.ValidationError):
			copy.insert(ignore_permissions=True)

	def test_duplicate_indicator_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			fx.plan(YEAR, indicators=[(self.ind, 1, 2), (self.ind, 1, 3)])

	def test_update_activity_by_responsible_or_r01_only(self):
		doc = fx.approve(self._plan(), self.r13)
		row = doc.activities[0].name
		stranger = fx.user("R11", prefix="plan-stranger")
		frappe.set_user(fx.user("R11", prefix="plan-owner"))
		annual_plan.update_activity(doc.name, row, "In Progress", "half done")
		frappe.set_user(stranger)
		with self.assertRaises(frappe.PermissionError):
			annual_plan.update_activity(doc.name, row, "Completed")
		frappe.set_user(self.r01)
		annual_plan.update_activity(doc.name, row, "Completed")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("IC Plan Activity", row, "status"), "Completed")
		with self.assertRaises(frappe.ValidationError):
			annual_plan.update_activity(doc.name, row, "Bogus")

	def test_year_summary_pools_months_and_judges_target(self):
		"""AC-6 (Q3): cộng dồn tử/mẫu số các tháng; kỳ chưa khóa → Tạm."""
		fx.indicator_value(self.ind, f"{YEAR}-01", 70, 100)
		fx.indicator_value(self.ind, f"{YEAR}-02", 90, 100, locked=0)
		fx.indicator_value(self.ind, f"{YEAR}-02", 1, 1, department=fx.required_department("Plan Ward"))
		doc = self._plan()
		doc.activities[0].status = "Completed"
		doc.save()
		result = annual_plan.year_summary(doc.name)
		row = result["indicators"][0]
		self.assertAlmostEqual(row["value"], 80.0)
		self.assertEqual(row["status"], "Met")
		self.assertEqual(row["latest_period"], f"{YEAR}-02")
		self.assertAlmostEqual(row["latest"], 90.0)
		self.assertTrue(result["provisional"])
		self.assertEqual((result["activities_completed"], result["activities_total"]), (1, 1))

	def test_year_summary_not_calculated_and_final(self):
		year = 2001
		fx.clear_plans(year)
		code = fx.indicator("T-PLAN-RATE", kind="Rate per 1000", direction="Lower is better", target=3)
		fx.indicator_value(code, f"{year}-03", 0, 0)
		doc = fx.plan(year, indicators=[(code, 3.4, 3)])
		result = annual_plan.year_summary(doc.name)
		self.assertIsNone(result["indicators"][0]["value"])
		self.assertEqual(result["indicators"][0]["status"], "Not calculated")
		self.assertFalse(result["provisional"])  # năm đã hết, mọi tháng có dữ liệu đã khóa

	def test_annual_value_rules(self):
		row = frappe._dict
		self.assertEqual(annual_plan.annual_value("Count", [row(numerator=2, denominator=0, sample_size=0)]), (2, ""))
		self.assertEqual(annual_plan.annual_value("Percentage", []), (None, "Not calculated"))
		self.assertEqual(
			annual_plan.annual_value("Percentage", [row(numerator=1, denominator=2, sample_size=2)], 5),
			(50.0, "Insufficient sample"),
		)
		self.assertEqual(annual_plan.judge(2.1, "", 3, "Lower is better"), "Met")
		self.assertEqual(annual_plan.judge(68, "", 85, "Higher is better"), "Not met")
		self.assertEqual(annual_plan.judge(68, "", 85, ""), "")
