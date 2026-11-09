"""Màn SCR-49 Đào tạo KSNK trong Page tc-ksnk (FEAT-059 AC-9; FR-M11-09..11; UC-42; A-131, A-135)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR49 = "public/js/ksnk/scr_49_dao_tao.js"

DATA = """
const data = {
	year: 2026, target: 80,
	basic: {
		departments: [
			{department: "D1", department_name: "Hồi sức <b>", employees: 48, trained: 47, rate: 97.9, rate_label: "97,9 %",
			 status: "ok", status_label: "Met", untrained: [{employee: "E9", employee_name: "BS. Z"}]},
			{department: "D2", department_name: "Cấp cứu", employees: 52, trained: 38, rate: 73.1, rate_label: "73,1 %",
			 status: "below", status_label: "Below target", untrained: []},
			{department: "D3", department_name: "Khoa trống", employees: 0, trained: 0, rate: null, rate_label: "—",
			 status: "na", status_label: "Not calculated", untrained: []},
		],
		total: {employees: 100, trained: 85, rate: 85.0, rate_label: "85,0 %"},
		untagged_events: 2,
	},
	core: {
		people: [
			{employee: "E1", employee_name: "ĐD. A", department_name: "Nội", groups: ["network"], passed: false, basis: null},
			{employee: "E2", employee_name: "BS. B", department_name: "Ngoại", groups: ["committee", "network"], passed: true,
			 basis: "certificate"},
		],
		total: {passed: 1, people: 2, rate: 50.0, rate_label: "50,0 %"},
	},
	trainees: {
		rows: [
			{name: "SV-2026-00231", school: "ĐH Y", department_name: "Ngoại", period_from: "2026-11-04",
			 trained_on: "2026-11-01", status: "Valid", status_label: "Valid", result: "Passed"},
			{name: "SV-2026-00233", school: "CĐ Y", department_name: "Nhi", period_from: "2026-11-04",
			 trained_on: "2026-11-05", status: "Trained After Start", status_label: "Trained After Start", result: "Passed"},
			{name: "SV-2026-00232", school: "ĐH Y", department_name: "Sản", period_from: "2026-11-04",
			 trained_on: null, status: "Not Trained", status_label: "Not Trained", result: ""},
		],
		late: 1, not_trained: 1,
	},
	can_remind: true,
};
const esc = TcKsnk.esc;
"""


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


class TestKsnkScr49(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR49], [["TcKsnk"], ["TcKsnkScr49"]], DATA + code)

	def test_status_badges_always_have_text(self):
		out = self._run(
			"""
			const s = TcKsnkScr49;
			emit({ok: s.badge("ok", "Met"), below: s.badge("below", "Below target"), na: s.badge("na", "Not calculated"),
				none: s.badge("none", "No target"), valid: s.traineeBadge("Valid", "Valid"),
				late: s.traineeBadge("Trained After Start", "Late"), not: s.traineeBadge("Not Trained", "Not trained")});
			"""
		)
		self.assertEqual(out["ok"]["cls"], "is-pass")
		self.assertEqual(out["below"]["cls"], "is-warn")
		self.assertEqual(out["na"]["cls"], "is-neutral")
		self.assertEqual(out["none"]["cls"], "is-neutral")
		self.assertEqual(out["valid"]["cls"], "is-pass")
		self.assertEqual(out["late"]["cls"], "is-fail")
		self.assertEqual(out["not"]["cls"], "is-fail")
		self.assertEqual(out["below"]["label"], "Below target")

	def test_kpi_cards(self):
		out = self._run("""emit({html: TcKsnkScr49.kpiHtml(data, esc)});""")
		html = out["html"]
		self.assertIn("85,0 %", html)
		self.assertIn("85/100", html)
		self.assertIn("50,0 %", html)
		self.assertIn("1/2", html)
		self.assertIn("≥ 80 %", html)
		self.assertEqual(html.count('<article class="tc-ksnk-kpi'), 3)
		self.assertIn("tc-ksnk-kpi is-pass", html)  # 85 % ≥ mục tiêu 80 %
		self.assertIn("tc-ksnk-kpi is-fail", html)  # còn sinh viên chưa đào tạo trước ngày bắt đầu

	def test_department_table_escapes_and_remind_links(self):
		out = self._run(
			"""emit({full: TcKsnkScr49.departmentsHtml(data, false, esc), ro: TcKsnkScr49.departmentsHtml(data, true, esc),
				noRight: TcKsnkScr49.departmentsHtml(Object.assign({}, data, {can_remind: false}), false, esc)});"""
		)
		html = out["full"]
		self.assertIn("Hồi sức &lt;b&gt;", html)
		self.assertNotIn("Hồi sức <b>", html)
		self.assertIn('data-action="remind"', html)
		self.assertIn('data-department="D1"', html)
		self.assertNotIn('data-department="D2"', html)  # không còn ai chưa học → không có nút nhắc
		self.assertIn("Below target", html)
		self.assertIn("Not calculated", html)
		self.assertIn("2 training events have no IC category", html)
		self.assertNotIn('data-action="remind"', out["ro"])
		self.assertNotIn('data-action="remind"', out["noRight"])

	def test_core_list_shows_only_people_not_passed(self):
		out = self._run("""emit({html: TcKsnkScr49.coreHtml(data, esc)});""")
		self.assertIn("ĐD. A", out["html"])
		self.assertNotIn("BS. B", out["html"])
		self.assertIn("Network member", out["html"])

	def test_trainee_table_and_warning(self):
		out = self._run(
			"""emit({html: TcKsnkScr49.traineesHtml(data, esc),
				none: TcKsnkScr49.traineesHtml({trainees: {rows: [], late: 0, not_trained: 0}}, esc)});"""
		)
		html = out["html"]
		self.assertIn("SV-2026-00233", html)
		self.assertIn("04/11/2026", html)  # ngày dd/mm/yyyy
		self.assertIn("tc-ksnk-code", html)
		self.assertIn("tc-ksnk-alert is-warn", html)  # đào tạo muộn: cảnh báo, không phải lỗi chặn (A-135 c)
		self.assertIn("1 trainees were trained after the internship start date", html)
		self.assertNotIn('role="alert"', html)
		self.assertIn("No trainees", out["none"])

	def test_actions(self):
		out = self._run("""emit({html: TcKsnkScr49.actionsHtml(data, esc)});""")
		self.assertIn('href="/app/training-event"', out["html"])
		self.assertIn("/app/query-report/IC Training by Department", out["html"])

	def test_block_alert_order_result_reason_action(self):
		out = self._run(
			"""emit({html: TcKsnkScr49.blockHtml({title: "Not sent", reason: "Pick a department", action: "Retry"}, esc)});"""
		)
		html = out["html"]
		self.assertIn('role="alert"', html)
		self.assertLess(html.index("Not sent"), html.index("Pick a department"))
		self.assertLess(html.index("Pick a department"), html.index("Retry"))

	def test_script_registers_and_uses_desk_helpers(self):
		script = _read(SCR49)
		self.assertIn('window.TcKsnkScreens["dao-tao"]', script)
		self.assertIn('"tracecore.v1.ksnk_training.status"', script)
		self.assertIn('"tracecore.v1.ksnk_training.remind"', script)
		self.assertNotIn("frappe.call(", script)
		self.assertNotIn("msgprint", script)
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", script))

	def test_css_kpi_uses_tokens(self):
		css = _read("ui/page/tc_ksnk/tc_ksnk.css")
		self.assertIn(".tc-ksnk .tc-ksnk-kpi", css)
		block = css[css.index(".tc-ksnk .tc-ksnk-kpi") :]
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", block))
