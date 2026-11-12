"""Màn SCR-67 Nước thải y tế trong Page tc-ksnk (FEAT-095; UC-58; FR-M15-08..13; A-153 §3.4, bổ sung 12/11/2026:
thanh thao tác cố định 3 nút và cửa sổ ghi đợt / xuất báo cáo / cập nhật GPMT như bản mẫu)."""

import os

import frappe

from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.ui import ksnk

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR67 = "public/js/ksnk/scr_67_nuoc_thai.js"

DATA = """
const data = {
	year: 2026, today: "2026-11-12", summary_only: false, can_decide: true, can_record: true, can_permit: true,
	perms: {"Wastewater Monitoring": {create: true, write: true}, "Wastewater Permit": {create: true, write: true},
		"Wastewater Point": {create: true, write: true}},
	kpis: {points: 2, on_time: 3, total_periods: 5, overdue: 1, flagged: 1, days_left_period: 49},
	permits: [{name: "GPMT-0154-V2", permit_no: "154/GPMT-UBND", standard: "QCVN 28:2010/BTNMT", standard_column: "B",
		effective_from: "2026-01-01", valid_until: "2027-01-31", issuing_authority: "UBND tỉnh <b>", factor_note: "K = 1,0",
		version_no: 2, days_to_expiry: 80, expiring: true, previous: "GPMT-0154-V1"}],
	drafts: 1,
	points: [{point: "NT-02", point_name: "Đầu ra HTXLNT"}, {point: "NT-03", point_name: "Điểm xả"}],
	flagged: [{point: "NT-03", point_name: "Điểm xả", monitoring: "QTNT-2026-0012", sampled_on: "2026-09-22",
		nc_status: "Suggested", nc_name: null, failed: ["Coliforms"]}],
	schedule: [
		{point: "NT-02", point_name: "Đầu ra HTXLNT", point_type: "Outlet", responsible_name: "Trần Văn Nam",
			frequency: 3, auto_only: false, awaiting_remonitor: 0, periods: [
			{label: "Q1/2026", start: "2026-01-01", end: "2026-03-31", status: "done", date: "2026-03-18", missing: []},
			{label: "Q2/2026", start: "2026-04-01", end: "2026-06-30", status: "over", missing: []},
			{label: "Q3/2026", start: "2026-07-01", end: "2026-09-30", status: "miss", date: "2026-09-22",
				missing: ["Coliforms"]},
			{label: "Q4/2026", start: "2026-10-01", end: "2026-12-31", status: "due", days_left: 49, missing: []}]},
		{point: "NT-04", point_name: "Trạm tự động", point_type: "Outlet", frequency: null, auto_only: true,
			periods: [{label: "2026", start: "2026-01-01", end: "2026-12-31", status: "na", missing: []}]}],
	latest: [
		{name: "QTNT-2026-0011", wastewater_point: "NT-02", point_name: "Đầu ra HTXLNT", point_type: "Outlet",
			sampled_on: "2026-09-22", supplier_name: "Trung tâm QT A", vimcerts_no: "VIMCERTS 112", report_no: "2610/KQ",
			overall_result: "Incomplete", missing: ["Coliforms"], results: [
				{parameter: "Coliforms", unit: "MPN/100mL", value: 0, limit_text: "≤ 5.000", result: null}]},
		{name: "QTNT-2026-0012", wastewater_point: "NT-03", point_name: "Điểm xả", point_type: "Discharge",
			sampled_on: "2026-09-22", supplier_name: "Trung tâm QT A", vimcerts_no: "VIMCERTS 112", report_no: "2611/KQ",
			overall_result: "Fail", nc_status: "Opened", nc_name: "NC-ENV-2026-0031", results: [
				{parameter: "Coliforms", unit: "MPN/100mL", value: 9300, limit_text: "≤ 5.000", result: "Fail"},
				{parameter: "Salmonella", unit: "Vk/100mL", below_detection: 1, limit_text: "KPH", result: "Pass"}]}],
	labs: [{supplier: "A", supplier_name: "Trung tâm QT A", vimcerts_no: "VIMCERTS 112", valid_until: "2027-06-30"},
		{supplier: "B", supplier_name: "Công ty Phân tích B", vimcerts_no: "VIMCERTS 087",
		valid_until: "2026-10-01", expired: true}],
};
const esc = TcKsnk.esc;
const viewer = Object.assign({}, data, {can_decide: false, can_record: false, can_permit: false, perms: {}});
"""


class TestScr67Screen(IsolatedTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR67], [["TcKsnk"], ["TcKsnkScr67"]], DATA + code)

	def test_registered_in_environment_group(self):
		screen = next(item for item in ksnk.SCREENS if item["slug"] == "nuoc-thai")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-67", "UC-58", "environment"))
		self.assertEqual(set(screen["roles"]), {"TC R01", "TC R02", "TC R11", "TC R13", "System Manager"})
		self.assertTrue(os.path.exists(os.path.join(frappe.get_app_path("tracecore"), *SCR67.split("/"))))

	def test_permit_card_schedule_cells_and_results_have_text_status(self):
		html = self._run("emit(TcKsnkScr67.pageHtml(data, esc));")
		self.assertIn("GPMT-0154-V2", html)
		self.assertIn("QCVN 28:2010/BTNMT · B", html)
		self.assertIn("80 days left", html)
		self.assertIn("UBND tỉnh &lt;b&gt;", html)
		for label in ("Monitored", "Overdue", "Missing parameters", "Due", "Not applicable"):
			self.assertIn(label, html)
		self.assertIn("Exceeded \u2013 awaiting re-monitoring", html)
		self.assertIn("✕ Exceeded", html)
		self.assertIn("VIMCERTS 087", html)
		self.assertIn('data-action="open-nc" data-name="QTNT-2026-0012"', html)
		self.assertIn('aria-current="date"', html)
		self.assertIn("is-current", html)

	def test_latest_table_has_next_step_row(self):
		html = self._run("emit(TcKsnkScr67.pageHtml(data, esc));")
		self.assertIn("NC / next step", html)
		self.assertIn("NC-ENV-2026-0031", html)
		self.assertIn('data-action="remonitor" data-point="NT-03" data-name="QTNT-2026-0012"', html)
		self.assertIn('data-action="supplement" data-point="NT-02"', html)
		self.assertIn("Add Coliforms", html)

	def test_fixed_action_bar_has_three_buttons_and_reasons(self):
		out = self._run(
			"""emit({r01: TcKsnkScr67.actionsHtml(data, esc),
			r11: TcKsnkScr67.actionsHtml(Object.assign({}, data, {can_permit: false}), esc),
			viewer: TcKsnkScr67.actionsHtml(viewer, esc),
			empty: TcKsnkScr67.actionsHtml(Object.assign({}, data, {permits: []}), esc)});"""
		)
		for key in ("r01", "r11", "viewer", "empty"):
			self.assertIn('class="tc-ww-actions"', out[key])
			for action in ("record", "export", "permit"):
				self.assertIn(f'data-action="{action}"', out[key])
		self.assertNotIn("disabled", out["r01"])
		self.assertIn('data-action="permit" disabled', out["r11"])
		self.assertIn("Only the head of infection control (R01) updates the permit", out["r11"])
		self.assertIn('data-action="record" disabled', out["viewer"])
		self.assertIn("This role can only view", out["viewer"])
		self.assertNotIn('data-action="export" disabled', out["viewer"])
		self.assertIn('data-action="record" disabled', out["empty"])
		self.assertIn("No approved permit yet", out["empty"])

	def test_viewer_gets_no_decision_or_follow_up_buttons(self):
		html = self._run("emit(TcKsnkScr67.pageHtml(viewer, esc));")
		self.assertNotIn("open-nc", html)
		self.assertNotIn('data-action="remonitor"', html)
		self.assertNotIn('data-action="new-version"', html)

	@bru("BRU-ENV-005")
	def test_dialog_judges_each_value_like_the_server(self):
		out = self._run(
			"""const j = TcKsnkScr67.judge;
			emit([j({min_value: 6, max_value: 9}, "9,2", false), j({max_value: 100}, "", true),
			j({detect_only: 1}, "2", false), j({min_value: 6.5, max_value: 8.5}, "", true),
			j({max_value: 100}, "", false), j({max_value: 5000}, "4600", false), TcKsnkScr67.parse("1.234,5"),
			TcKsnkScr67.summaryHtml({pass: 2, fail: 1, missing: 0}, esc),
			TcKsnkScr67.summaryHtml({pass: 2, fail: 0, missing: 1}, esc)]);"""
		)
		self.assertEqual(out[:7], ["fail", "pass", "fail", "fail", "none", "pass", 1234.5])
		self.assertIn("The round will fail", out[7])
		self.assertIn("missing parameters", out[8])

	def test_record_dialog_rows_and_lab_options(self):
		out = self._run(
			"""emit({rows: TcKsnkScr67.paramRowsHtml([{parameter: "pH", unit: "-", limit_text: "6,5 - 8,5",
				min_value: 6.5, max_value: 8.5}, {parameter: "Salmonella", unit: "Vk", limit_text: "KPH",
				detect_only: 1}], esc), labs: TcKsnkScr67.labOptions(data.labs, "2026-10-05", esc)});"""
		)
		self.assertIn('data-param="pH"', out["rows"])
		self.assertIn('data-kph="Salmonella"', out["rows"])
		self.assertIn("Not entered", out["rows"])
		self.assertIn("VIMCERTS 112", out["labs"])
		self.assertIn('value="B" disabled', out["labs"])

	def test_summary_only_and_empty_states(self):
		out = self._run(
			"""emit({summary: TcKsnkScr67.pageHtml(Object.assign({}, data, {summary_only: true}), esc),
			empty: TcKsnkScr67.pageHtml(Object.assign({}, data, {permits: [], schedule: [], latest: []}), esc)});"""
		)
		self.assertIn("3/5", out["summary"])
		self.assertNotIn("QTNT-2026-0012", out["summary"])
		self.assertIn("No approved environmental permit yet", out["empty"])
