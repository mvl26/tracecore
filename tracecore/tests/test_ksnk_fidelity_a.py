"""Giai đoạn 2 (nhóm A) — SCR-47..50 bám bố cục ảnh duyệt docs/design-refs/v1.12."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR47 = "public/js/ksnk/scr_47_co_cau.js"
SCR48 = "public/js/ksnk/scr_48_ke_hoach.js"
SCR49 = "public/js/ksnk/scr_49_dao_tao.js"
SCR50 = "public/js/ksnk/scr_50_mau_phieu.js"

HEAD = """
frappe.user = {has_role: () => true};
const esc = TcKsnk.esc;
const ctx = {filters: {}, departments: [], readOnly: false, esc, state: (k, m) => "<state>" + m + "</state>"};
"""


class TestKsnkFidelityA(FrappeTestCase):
	def run47(self, script):
		return run_js(self, [SHELL, SCR47], [["TcKsnk"], ["TcKsnkScr47"]], HEAD + script)

	def run48(self, script):
		return run_js(self, [SHELL, SCR48], [["TcKsnk"], ["TcKsnkScr48"]], HEAD + script)

	def run49(self, script):
		return run_js(self, [SHELL, SCR49], [["TcKsnk"], ["TcKsnkScr49"]], HEAD + script)

	def run50(self, script):
		return run_js(self, [SHELL, SCR50], [["TcKsnk"], ["TcKsnkScr50"]], HEAD + script)

	def test_scr47_committee_and_network_side_by_side(self):
		out = self.run47(
			"""
			const data = {missing_total: 0, settings: {}, components: [], departments: [], profile: null,
				committee: {name: "HDK-1", decision_no: "152/QĐ-BV", valid_from: "2026-01-15", valid_to: "2029-01-14",
					members: [], missing_representatives: []}};
			emit({h: TcKsnkScr47.pageHtml(data, false, esc)});
			"""
		)["h"]
		cols = out.index("tc-ksnk-cols")
		self.assertLess(out.index("IC Committee"), out.index("IC network by department"))
		self.assertLess(cols, out.index("IC Committee"))
		self.assertIn('class="form-control tc-ksnk-code" readonly value="152/QĐ-BV"', out)
		self.assertIn("15/01/2026 – 14/01/2029", out)

	def test_scr47_empty_committee_keeps_frame(self):
		out = self.run47(
			"""
			const data = {missing_total: 1, settings: {}, components: [], departments: [], committee: null};
			emit({h: TcKsnkScr47.pageHtml(data, false, esc)});
			"""
		)["h"]
		self.assertIn("No committee in force.", out)
		self.assertIn("IC network by department", out)

	def test_scr48_plan_tab_shows_documents_and_meeting_columns(self):
		out = self.run48(
			"""
			const plan = {name: "KH-1", year: 2026, docstatus: 1, created_by: "A", total_budget_vnd: 0,
				activities_total: 0, activities_completed: 0, indicators: [], activities: []};
			const data = {year: 2026, plan, documents: [], meeting: null, open_resolutions: []};
			emit({h: TcKsnkScr48.pageHtml(data, ctx)});
			"""
		)["h"]
		self.assertIn("tc-ksnk-cols", out)
		self.assertIn("Internal document register", out)
		self.assertIn("Latest committee meeting", out)
		self.assertLess(out.index("Activities"), out.index("Internal document register"))

	def test_scr49_year_is_select(self):
		out = self.run49(
			"""
			emit({h: TcKsnkScr49.filtersHtml({year: 2026}, ctx, esc)});
			"""
		)["h"]
		self.assertIn('<select class="form-control" data-filter="year">', out)
		self.assertIn('<option value="2026" selected>2026</option>', out)
		self.assertNotIn('type="number"', out)

	def test_scr50_tags_critical_label_and_coverage_bar(self):
		out = self.run50(
			"""
			const detail = {name: "MP-PNC-V2", title: "PPE", status: "Draft", can_edit: false, version_no: 2,
				audit_type: "Standard Precautions - PPE", scoring_method: "Weighted Score",
				items: [{item_code: "PNC-01", section: "PPE", question: "Q", answer_type: "Pass/Fail", weight: 2, is_critical: 1}]};
			const sched = {schedules: [{name: "LGS-1", template_title: "T", coverage: [{department: "ICU", label: "ICU 4/10"}],
				frequency: "Monthly", target_count: 30, assignee_name: "A", coverage_pct: 42}]};
			emit({d: TcKsnkScr50.detailHtml(detail, {}, esc), s: TcKsnkScr50.schedulesHtml(sched, esc)});
			"""
		)
		self.assertIn('<code class="tc-ksnk-tag">MP-PNC-V2</code>', out["d"])
		self.assertIn("Yes", out["d"])
		self.assertIn("tc-ksnk-progress", out["s"])
		self.assertIn("width: 42%", out["s"])
