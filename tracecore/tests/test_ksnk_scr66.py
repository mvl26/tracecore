"""SCR-66 Bảng chỉ số KSNK đầy đủ — hàm hiển thị của màn (FEAT-065 AC-065-01, 04, 15; BRU-RPT-001; FR-M9-24.1:
trạng thái bằng chữ, không chỉ bằng màu)."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.test_ksnk_page import SCR66, SHELL

BOARD = """
const esc = TcKsnk.esc;
const periods = ["2031-08", "2031-09", "2031-10"];
const hh = {
	code: "HH-01", indicator_name: "Hand hygiene", measure_group: "Hand Hygiene", kind: "Percentage",
	target: 80, target_direction: "Higher is better", status: "Not met",
	latest: {value: 78.4, sample_size: 1214, locked: 1, status: "Not met"},
	values: {"2031-08": {value: 75.2}, "2031-09": {value: 77.9}, "2031-10": {value: 78.4, sample_size: 1214, locked: 1}},
};
const vap = {
	code: "HAI-02", indicator_name: "VAP", measure_group: "Invasive Procedure", kind: "Rate per 1000",
	target: 7, target_direction: "Lower is better", status: "Not calculated",
	latest: {value: null, sample_size: 0, locked: 0, status: "Not calculated"},
	values: {"2031-10": {value: null, locked: 0}},
};
const data = {
	year: 2031, plan: {name: "KH-2031-01"}, period: "2031-10", periods, table_periods: periods, locked: true,
	rows: [hh, vap], kpis: ["HH-01", "HAI-02"], todos: [], council_report: null,
	chart: {
		indicator: "HH-01", indicator_name: "Hand hygiene", kind: "Percentage", target: 80,
		target_direction: "Higher is better", period: "2031-10", options: [{code: "HH-01", indicator_name: "Hand hygiene"}],
		rows: [
			{department: "A", department_name: "ICU", value: 86, status: "Met"},
			{department: "B", department_name: "Dialysis", value: 61, status: "Not met"},
		],
	},
};
"""


class TestScr66Display(FrappeTestCase):
	def run_board(self, script):
		return run_js(self, [SHELL, SCR66], [["TcKsnk"], ["TcKsnkScr66"]], BOARD + script)

	def test_status_text_depends_on_direction(self):
		out = self.run_board(
			"""
			const s = TcKsnkScr66;
			emit({
				high: s.statusBadge("Not met", "Higher is better"),
				low: s.statusBadge("Not met", "Lower is better"),
				none: s.statusBadge("No data"),
			});
			"""
		)
		self.assertEqual(out["high"], {"cls": "is-warn", "label": "Not met"})
		self.assertEqual(out["low"], {"cls": "is-fail", "label": "Above threshold"})
		self.assertEqual(out["none"]["label"], "No data")

	def test_kpis_table_and_not_calculated(self):
		out = self.run_board(
			"""
			const s = TcKsnkScr66;
			emit({kpis: s.kpisHtml(data, esc), table: s.tableHtml(data, esc), cell: s.cellText({value: null}, "Rate per 1000"),
				missing: s.cellText(null, "Percentage"), target: s.targetText(hh)});
			"""
		)
		self.assertIn("78,4 %", out["kpis"])
		self.assertIn("1.214 sample", out["kpis"])
		self.assertIn("tc-ksnk-kpi is-warn", out["kpis"])
		self.assertIn("Not calculated", out["kpis"])  # BRU-RPT-001: không hiện 0
		self.assertNotIn(">0 ‰<", out["table"])
		self.assertIn("Provisional", out["table"])
		self.assertIn("10/2031", out["table"])
		self.assertIn('role="img"', out["table"])
		self.assertEqual(out["cell"], "Not calculated")
		self.assertEqual(out["missing"], "—")
		self.assertEqual(out["target"], "≥ 80 %")

	def test_sparkline_has_text_alternative(self):
		out = self.run_board(
			"""
			const s = TcKsnkScr66;
			emit({line: s.sparkline(hh, periods, esc), empty: s.sparkline(vap, periods, esc)});
			"""
		)
		self.assertIn("<polyline", out["line"])
		self.assertIn("08/2031 75,2 %", out["line"])
		self.assertIn("tc-ksnk-spark-target", out["line"])
		self.assertIn("Not enough data", out["empty"])

	def test_chart_marks_below_target_with_symbol(self):
		out = self.run_board("emit(TcKsnkScr66.chartHtml(data.chart, esc));")
		self.assertIn("61 % ↓", out)
		self.assertIn("86 %", out)
		self.assertNotIn("86 % ↓", out)
		self.assertIn("is-below", out)

	def test_self_assessment_actions_by_state(self):
		out = self.run_board(
			"""
			const s = TcKsnkScr66;
			const rows = [{criterion: "A", criterion_text: "A", source_hint: "", source: "Manual",
				status: "Met", source_ref: "", evidence: ""}];
			const base = {year: 2031, name: "TDG-2031", rows};
			emit({
				draft: s.selfHtml(Object.assign({}, base, {docstatus: 0, can_manage: true, editable: true}), esc),
				sub: s.selfHtml(Object.assign({}, base, {docstatus: 1, can_manage: true, editable: false}), esc),
				ro: s.selfHtml(Object.assign({}, base, {docstatus: 1, can_manage: false, editable: false}), esc),
				none: s.selfHtml({year: 2032, name: null, rows: [], can_manage: true, editable: false}, esc),
			});
			"""
		)
		form = "/app/ic-self-assessment/TDG-2031"
		for key in ("draft", "sub", "ro"):
			self.assertIn(form, out[key])
			self.assertIn("printview", out[key])
		self.assertIn("sa-submit", out["draft"])
		self.assertIn("sa-save", out["draft"])
		self.assertNotIn("sa-submit", out["sub"])
		self.assertNotIn("sa-prepare", out["sub"])
		self.assertIn("cancel or amend", out["sub"])
		self.assertIn("/app/ic-self-assessment/new", out["sub"])
		self.assertNotIn("/app/ic-self-assessment/new", out["ro"])
		self.assertNotIn("cancel or amend", out["ro"])
		self.assertIn("sa-prepare", out["none"])

	def test_todos_and_self_assessment(self):
		out = self.run_board(
			"""
			const s = TcKsnkScr66;
			const todos = [{severity: "error", title: "3 departments have no census", detail: "ICU", link: "/app/x"},
				{severity: "info", title: "Report ready", detail: "", link: ""}];
			const sa = {year: 2031, name: "TDG-2031", docstatus: 0, can_manage: true, editable: true, rows: [
				{criterion: "QD38-PLAN", criterion_text: "Plan approved", source_hint: "M11", source: "Auto",
				 status: "Met", source_ref: "KH-2031-01", evidence: ""},
				{criterion: "QD38-IT", criterion_text: "IT", source_hint: "Manual", source: "Manual",
				 status: "Not assessed", source_ref: "", evidence: ""}]};
			emit({todos: s.todosHtml(todos, esc), none: s.todosHtml([], esc), sa: s.selfHtml(sa, esc),
				ro: s.selfHtml(Object.assign({}, sa, {can_manage: false, editable: false, docstatus: 1}), esc),
				empty: s.selfHtml({year: 2031, name: null, rows: [], can_manage: false}, esc)});
			"""
		)
		self.assertIn("3 departments have no census", out["todos"])
		self.assertIn('href="/app/x"', out["todos"])
		self.assertIn("is-info", out["todos"])
		self.assertIn("Nothing to handle", out["none"])
		self.assertIn("Met (automatic)", out["sa"])
		self.assertIn('data-action="sa-submit"', out["sa"])
		self.assertIn('data-sa-status="QD38-IT"', out["sa"])
		self.assertNotIn("data-sa-status", out["ro"])
		self.assertIn("Submitted", out["ro"])
		self.assertIn("not prepared yet", out["empty"])
