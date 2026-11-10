"""Tự đánh giá chất lượng KSNK hằng năm và tổng kết năm (FEAT-072 AC-5..AC-7; FR-M11-13, FR-M11-13.1, FR-M11-06;
BRU-AUD-001; UC-42 bước 6; A-149 Q3, Q4).

Phiếu tự đánh giá là `Audit Session` của mẫu loại "Quality Self-Assessment" đã duyệt, tạo bằng `frappe.get_doc` (không
import M12).
"""

import frappe
from frappe.utils import getdate, today

from tracecore.infection_program import annual_plan, improvement, plan_print, quality_review
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.patches.v0_1 import a149_ic_improvement_seed
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Supplier", "Incident CAPA", "Department", "User", "Employee"]
YEAR = getdate(today()).year
ITEMS = (("TDG-A", "Organization", "Council active"), ("TDG-B", "Surveillance", "HAI surveillance"))


def self_template(code="T-TDG-072", items=ITEMS):
	name = frappe.db.get_value("Audit Template", {"template_code": code, "docstatus": 1}, "name")
	if name:
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Audit Template",
			"template_code": code,
			"title": "IC self-assessment",
			"audit_type": quality_review.AUDIT_TYPE,
			"scoring_method": "Weighted Score",
			"effective_from": f"{YEAR - 2}-01-01",
			"items": [
				{"item_code": c, "section": s, "question": q, "answer_type": "Pass/Fail", "weight": 1}
				for c, s, q in items
			],
		}
	).insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def assess(year, answers, department):
	observer = frappe.db.get_value("Employee", {"first_name": "TDG 072 Observer"}, "name")
	observer = observer or factories.make_employee(first_name="TDG 072 Observer").name
	doc = frappe.get_doc(
		{
			"doctype": "Audit Session",
			"audit_template": self_template(),
			"department": department,
			"audit_date": f"{year}-01-15",
			"observer": observer,
			"answers": [
				{"item_code": code, "answer": answer, "note": "x" if answer == "Fail" else ""}
				for code, answer in answers.items()
			],
		}
	)
	doc.flags.tc_replay = True  # phiếu năm trước dùng phiên bản mẫu có hiệu lực lúc đó
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


class TestQualityReview(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.lang = "en"
		frappe.db.sql(
			"update `tabAudit Session` set docstatus = 2 where audit_type = %s and docstatus = 1",
			quality_review.AUDIT_TYPE,
		)
		self.dept = factories.make_department("KSNK TDG 072")

	@bru("BRU-AUD-001")
	def test_two_consecutive_years_side_by_side(self):
		assess(YEAR - 1, {"TDG-A": "Fail", "TDG-B": "Pass"}, self.dept)
		this = assess(YEAR, {"TDG-A": "Pass", "TDG-B": "Pass"}, self.dept)
		data = quality_review.compare(YEAR)
		self.assertEqual((data["year"], data["previous_year"]), (YEAR, YEAR - 1))
		self.assertEqual(data["current"]["name"], this.name)
		self.assertEqual(data["current"]["score_pct"], 100.0)
		self.assertEqual(data["previous"]["score_pct"], 50.0)
		self.assertTrue(data["both"])
		rows = {row["item_code"]: row for row in data["items"]}
		self.assertEqual((rows["TDG-A"]["current"], rows["TDG-A"]["previous"]), ("Pass", "Fail"))
		self.assertTrue(rows["TDG-A"]["changed"])
		self.assertFalse(rows["TDG-B"]["changed"])
		self.assertEqual(rows["TDG-A"]["current_label"], "Pass")

	def test_only_current_year(self):
		assess(YEAR, {"TDG-A": "Pass", "TDG-B": "Fail"}, self.dept)
		data = quality_review.compare(YEAR)
		self.assertIsNone(data["previous"])
		self.assertFalse(data["both"])
		self.assertEqual([row["previous"] for row in data["items"]], ["", ""])

	def test_latest_posted_session_of_the_year_wins(self):
		assess(YEAR, {"TDG-A": "Fail", "TDG-B": "Fail"}, self.dept)
		later = assess(YEAR, {"TDG-A": "Pass", "TDG-B": "Fail"}, self.dept)
		self.assertEqual(quality_review.latest(YEAR)["name"], later.name)
		self.assertIsNone(quality_review.latest(YEAR - 5))

	def test_none_at_all(self):
		data = quality_review.compare(YEAR)
		self.assertEqual((data["current"], data["previous"], data["items"]), (None, None, []))

	def test_active_template_for_new_form(self):
		self_template()
		approved = frappe.get_all(
			"Audit Template", filters={"audit_type": quality_review.AUDIT_TYPE, "docstatus": 1}, pluck="name"
		)
		self.assertIn(quality_review.active_template(), approved)


class TestYearSummary(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.lang = "en"
		frappe.db.sql(
			"update `tabAudit Session` set docstatus = 2 where audit_type = %s and docstatus = 1",
			quality_review.AUDIT_TYPE,
		)
		frappe.db.delete(improvement.DOCTYPE)
		fx.clear_plans(YEAR - 1)
		self.dept = factories.make_department("KSNK TDG 072")

	def _plan(self, year):
		return fx.plan(year, indicators=[(fx.indicator("T-PLAN-072"), 70, 80)])

	def test_year_summary_has_improvement_and_self_assessment(self):
		year = YEAR - 1
		frappe.get_doc(
			{
				"doctype": improvement.DOCTYPE,
				"project_type": "Quality Improvement",
				"title": "VST Cấp cứu",
				"start_date": f"{year}-02-01",
				"end_date": f"{year}-09-30",
				"status": improvement.COMPLETED,
				"result_summary": "58 % → 69 %",
			}
		).insert(ignore_permissions=True)
		session = assess(year, {"TDG-A": "Pass", "TDG-B": "Fail"}, self.dept)
		plan = self._plan(year)
		result = annual_plan.year_summary(plan.name)
		self.assertEqual(result["improvement_completed"], 1)
		self.assertEqual(result["self_assessment"]["name"], session.name)
		self.assertEqual(result["self_assessment"]["score_pct"], 50.0)
		context = plan_print.tc_ic_plan_context(plan.name)
		self.assertEqual(context["improvement_completed"], "1")
		self.assertIn("50", context["self_assessment"])

	def test_year_summary_without_data(self):
		plan = self._plan(YEAR - 1)
		result = annual_plan.year_summary(plan.name)
		self.assertEqual(result["improvement_completed"], 0)
		self.assertIsNone(result["self_assessment"])
		self.assertEqual(plan_print.tc_ic_plan_context(plan.name)["self_assessment"], "—")


class TestA149Patch(IsolatedTestCase):
	def test_fills_qd38_qi_only_when_empty(self):
		if not frappe.db.exists("IC QD38 Criterion", "QD38-QI"):
			self.skipTest("QD38 seed missing")
		frappe.db.set_value("IC QD38 Criterion", "QD38-QI", "check_method", "")
		a149_ic_improvement_seed.execute()
		self.assertEqual(
			frappe.db.get_value("IC QD38 Criterion", "QD38-QI", "check_method"), improvement.SELF_CHECK_KEY
		)
		frappe.db.set_value("IC QD38 Criterion", "QD38-QI", "check_method", "hospital_method")
		a149_ic_improvement_seed.execute()
		self.assertEqual(
			frappe.db.get_value("IC QD38 Criterion", "QD38-QI", "check_method"), "hospital_method"
		)

	def test_seeds_survey_templates(self):
		a149_ic_improvement_seed.execute()
		self.assertTrue(frappe.db.exists("Audit Template", {"template_code": "TDG-KSNK"}))
		self.assertTrue(frappe.db.exists("Audit Template", {"template_code": "CAT-NGANG"}))
