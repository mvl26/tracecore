"""Màn SCR-67 Nước thải y tế trong Page tc-ksnk (FEAT-095; UC-58; FR-M15-08..13; A-153 §3.4)."""

import os

import frappe

from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase
from tracecore.ui import ksnk

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR67 = "public/js/ksnk/scr_67_nuoc_thai.js"

DATA = """
const data = {
	year: 2026, today: "2026-11-12", summary_only: false, can_decide: true,
	perms: {"Wastewater Monitoring": {create: true, write: true}, "Wastewater Permit": {create: true, write: true},
		"Wastewater Point": {create: true, write: true}},
	kpis: {points: 2, on_time: 3, total_periods: 5, overdue: 1, flagged: 1, days_left_period: 49},
	permits: [{name: "GPMT-0154-V2", permit_no: "154/GPMT-UBND", standard: "QCVN 28:2010/BTNMT", standard_column: "B",
		effective_from: "2026-01-01", valid_until: "2027-01-31", issuing_authority: "UBND tỉnh <b>", factor_note: "K = 1,0",
		days_to_expiry: 80, expiring: true, previous: "GPMT-0154-V1"}],
	drafts: 1,
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
	latest: [{name: "QTNT-2026-0012", point: "NT-03", point_name: "Điểm xả", point_type: "Discharge",
		sampled_on: "2026-09-22", supplier_name: "Trung tâm QT A", vimcerts_no: "VIMCERTS 112", report_no: "2611/KQ",
		overall_result: "Fail", nc_status: "Suggested", results: [
			{parameter: "Coliforms", unit: "MPN/100mL", value: 9300, limit_text: "≤ 5.000", result: "Fail"},
			{parameter: "Salmonella", unit: "Vk/100mL", below_detection: 1, limit_text: "KPH", result: "Pass"}]}],
	labs: [{supplier: "B", supplier_name: "Công ty Phân tích B", vimcerts_no: "VIMCERTS 087",
		valid_until: "2026-10-01", expired: true}],
};
const esc = TcKsnk.esc;
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
		self.assertIn("Coliforms", html)
		self.assertIn("Exceeded \u2013 awaiting re-monitoring", html)
		self.assertIn("✕ Exceeded", html)
		self.assertIn("VIMCERTS 087", html)
		self.assertIn('data-action="open-nc" data-name="QTNT-2026-0012"', html)
		self.assertIn("is_remonitor_of=QTNT-2026-0012", html)
		self.assertIn("/app/query-report/Wastewater Monitoring Summary", html)
		self.assertIn('data-action="new-version"', html)
		self.assertIn('aria-current="date"', html)

	def test_viewer_without_rights_gets_no_write_buttons(self):
		html = self._run(
			"""emit(TcKsnkScr67.pageHtml(Object.assign({}, data, {can_decide: false, perms: {}}), esc));"""
		)
		self.assertNotIn("open-nc", html)
		self.assertNotIn('data-action="new-version"', html)
		self.assertNotIn("/app/wastewater-monitoring/new", html)

	def test_summary_only_and_empty_states(self):
		out = self._run(
			"""emit({summary: TcKsnkScr67.pageHtml(Object.assign({}, data, {summary_only: true}), esc),
			empty: TcKsnkScr67.pageHtml(Object.assign({}, data, {permits: [], schedule: [], latest: []}), esc)});"""
		)
		self.assertIn("3/5", out["summary"])
		self.assertNotIn("QTNT-2026-0012", out["summary"])
		self.assertIn("No approved environmental permit yet", out["empty"])
		self.assertIn("/app/wastewater-permit/new", out["empty"])
