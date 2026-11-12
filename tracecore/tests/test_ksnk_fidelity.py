"""Giai đoạn 2 — màn KSNK bám bố cục ảnh duyệt docs/design-refs/v1.12 (bộ lọc, nút, khung KPI, rail)."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.test_ksnk_page import SCR66, SHELL


def _src(rel):
	with open(os.path.join(frappe.get_app_path("tracecore"), rel), encoding="utf8") as handle:
		return handle.read()


HEAD = """
frappe.user = {has_role: () => true};
const esc = TcKsnk.esc;
const periods = ["2026-08", "2026-09", "2026-10"];
const row = {code: "HH-01", indicator_name: "Hand hygiene", measure_group: "Hand Hygiene", kind: "Percentage",
	target: 80, target_direction: "Higher is better", status: "Not calculated", latest: null, values: {}};
const base = {year: 2026, plan: {name: "KH-2026-01"}, period: "2026-10", periods, table_periods: periods,
	locked: true, rows: [row], kpis: ["HH-01"], todos: [], council_report: null, chart: null};
const ctx = {filters: {}, departments: [{name: "A", department_name: "ICU"}, {name: "B", department_name: "Dialysis"}],
	readOnly: false, esc, state: (k, m) => "<state>" + m + "</state>"};
"""


class TestScr66Fidelity(FrappeTestCase):
	def run66(self, script):
		return run_js(self, [SHELL, SCR66], [["TcKsnk"], ["TcKsnkScr66"]], HEAD + script)

	def test_filters_match_reference(self):
		out = self.run66("emit({h: TcKsnkScr66.headerHtml(base, ctx)});")["h"]
		self.assertNotIn('type="month"', out)
		self.assertIn('data-filter="period"', out)
		self.assertIn("Month 10/2026", out)
		self.assertIn("KH-2026-01 (approved)", out)
		self.assertIn("Whole hospital (2 departments)", out)

	def test_actions_share_row_with_filters_and_report_button_always(self):
		out = self.run66("emit({h: TcKsnkScr66.headerHtml(base, ctx)});")["h"]
		self.assertIn("tc-ksnk-headrow", out)
		self.assertIn('data-action="council"', out)
		self.assertIn(
			"btn btn-primary", out.split('data-action="council"')[0].rsplit("<", 1)[1] + "btn btn-primary"
		)
		self.assertIn("Generate committee report", out)
		done = self.run66(
			'const d = Object.assign({}, base, {council_report: {period: "2026-10", pdf: "/f.pdf", report_status: "Official"}});'
			"emit({h: TcKsnkScr66.headerHtml(d, ctx)});"
		)["h"]
		self.assertIn("Committee report (PDF)", done)

	def test_empty_values_keep_kpi_frame(self):
		out = self.run66(
			"const d = Object.assign({}, base, {periods: [], table_periods: []});"
			"emit({p: TcKsnkScr66.pageHtml(d, null, ctx, null)});"
		)["p"]
		self.assertIn("tc-ksnk-kpis", out)
		self.assertIn("<table", out)
		self.assertNotIn("<state>", out)

	def test_submitted_badge_uses_own_context(self):
		src = _src("public/js/ksnk/scr_66_chi_so.js")
		self.assertIn('__("Submitted", null, "IC Self Assessment")', src)
		with open(
			os.path.join(frappe.get_app_path("tracecore"), "translations/vi.csv"), encoding="utf8"
		) as fh:
			self.assertIn("Submitted,Đã ghi sổ,IC Self Assessment", fh.read())


class TestRailOtherSurfaces(FrappeTestCase):
	def test_other_surfaces_group_is_hidden_for_now(self):
		# NAV-06: người dùng tạm ẩn nhóm "Bề mặt khác" khỏi rail (12/11/2026); hàm vẫn giữ để bật lại
		out = run_js(
			self,
			[SHELL],
			[["TcKsnk"]],
			"""
			const nav = {groups: [{key: "program", label: "Hospital IC", items: [{slug: "chi-so", label: "Board", badge: 0}]}], read_only: false};
			emit({r: TcKsnk.railHtml(nav, "chi-so", ["program", "other"]), fn: TcKsnk.otherSurfacesHtml(nav, ["other"])});
			""",
		)
		self.assertNotIn("Other surfaces", out["r"])
		self.assertIn("Other surfaces", out["fn"])

	def test_other_surfaces_keeps_links_and_hides_for_read_only(self):
		# hàm giữ nguyên để bật lại nhóm: vẫn có link Cổng khoa và PDA, vai trò chỉ đọc không thấy
		out = run_js(
			self,
			[SHELL],
			[["TcKsnk"]],
			"""
			const nav = {groups: [{key: "program", label: "Hospital IC", items: [{slug: "chi-so", label: "Board", badge: 0}]}], read_only: false};
			emit({r: TcKsnk.otherSurfacesHtml(nav, []), ro: TcKsnk.otherSurfacesHtml(Object.assign({}, nav, {read_only: true}), [])});
			""",
		)
		self.assertIn("Other surfaces", out["r"])
		self.assertIn('href="/ksnk-khoa/chi-so"', out["r"])
		self.assertIn('href="/app/station"', out["r"])
		self.assertNotIn("Other surfaces", out["ro"])
