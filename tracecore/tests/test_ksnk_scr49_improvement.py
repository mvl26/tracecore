"""SCR-49 khối cải tiến chất lượng & tự đánh giá (FEAT-072 AC-6, AC-12; FR-M11-12, FR-M11-13.1; UC-42; A-149)."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR49 = "public/js/ksnk/scr_49_dao_tao.js"

DATA = """
const imp = {
	year: 2026, can_edit: true, template: "MP-TDG-KSNK-V1",
	improvement: {
		total: 2, completed: 1, in_progress: 1,
		projects: [
			{name: "CI-2026-001", title: "Tăng VST <i>", project_type_label: "Quality Improvement", status: "Check (C)",
			 status_label: "Check (C)", result_summary: "58 % → 69 %"},
			{name: "CI-2026-003", title: "Giảm CAUTI", project_type_label: "Research Project", status: "Completed",
			 status_label: "Completed", result_summary: ""},
		],
	},
	self_assessment: {
		year: 2026, previous_year: 2025, both: true,
		current: {name: "GS-2026-00001", score_pct: 88.9}, previous: {name: "GS-2025-00001", score_pct: 66.7},
		items: [
			{item_code: "TDG-01", section: "Organization", question: "Council active", current_label: "Pass",
			 previous_label: "Fail", changed: true},
			{item_code: "TDG-02", section: "Organization", question: "Plan approved", current_label: "Pass",
			 previous_label: "Pass", changed: false},
		],
	},
};
const esc = TcKsnk.esc;
"""


class TestKsnkScr49Improvement(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR49], [["TcKsnk"], ["TcKsnkScr49"]], DATA + code)

	def test_kpi_card_counts_projects(self):
		out = self._run("""emit({html: TcKsnkScr49.improvementKpi(imp, esc)});""")
		self.assertIn("<b>2</b>", out["html"])
		self.assertIn("1 completed · 1 in progress", out["html"])

	def test_projects_table_has_text_stage_and_escapes(self):
		out = self._run(
			"""emit({html: TcKsnkScr49.improvementHtml(imp, esc),
				ro: TcKsnkScr49.improvementHtml(Object.assign({}, imp, {can_edit: false}), esc),
				none: TcKsnkScr49.improvementHtml({improvement: {projects: []}, self_assessment: {items: []}}, esc)});"""
		)
		html = out["html"]
		self.assertIn("CI-2026-001", html)
		self.assertIn("Tăng VST &lt;i&gt;", html)
		self.assertIn('tc-ksnk-badge is-info">Check (C)', html)
		self.assertIn('tc-ksnk-badge is-pass">Completed', html)
		self.assertIn("58 % → 69 %", html)
		self.assertIn("/app/ic-improvement-project/new", html)
		self.assertNotIn("/app/ic-improvement-project/new", out["ro"])
		self.assertIn("No improvement projects", out["none"])

	def test_self_assessment_two_years_side_by_side(self):
		out = self._run(
			"""emit({html: TcKsnkScr49.selfAssessmentHtml(imp, esc),
				one: TcKsnkScr49.selfAssessmentHtml(Object.assign({}, imp, {template: null,
					self_assessment: Object.assign({}, imp.self_assessment, {both: false, previous: null})}), esc),
				none: TcKsnkScr49.selfAssessmentHtml({self_assessment: {items: []}}, esc)});"""
		)
		html = out["html"]
		self.assertIn("2026 vs 2025", html)
		self.assertIn("88,9 %", html)
		self.assertIn("66,7 %", html)
		self.assertIn("Changed", html)
		self.assertIn("/app/audit-session/new?audit_template=MP-TDG-KSNK-V1", html)
		self.assertIn("Only one of the two years", out["one"])
		self.assertIn("No approved self-assessment template", out["one"])
		self.assertIn("No self-assessment posted", out["none"])

	def test_page_puts_trainees_and_improvement_in_two_columns(self):
		out = self._run(
			"""
			const data = {year: 2026, target: 80, can_remind: false,
				basic: {departments: [], total: {employees: 0, trained: 0, rate: null, rate_label: "—"}, untagged_events: 0},
				core: {people: [], total: {passed: 0, people: 0, rate: null, rate_label: "—"}},
				trainees: {rows: [], late: 0, not_trained: 0}};
			emit({html: TcKsnkScr49.pageHtml(data, {departments: [], filters: {}}, esc, imp),
				old: TcKsnkScr49.pageHtml(data, {departments: [], filters: {}}, esc)});
			"""
		)
		self.assertIn("tc-ksnk-cols", out["html"])
		self.assertEqual(out["html"].count('<article class="tc-ksnk-kpi'), 4)
		self.assertEqual(out["old"].count('<article class="tc-ksnk-kpi'), 3)
