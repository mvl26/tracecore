"""Màn SCR-47 Cơ cấu KSNK trong Page tc-ksnk (FEAT-057 AC-11; FR-M11-01.3, FR-M11-02, FR-M11-03; A-131)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR47 = "public/js/ksnk/scr_47_co_cau.js"

DATA = """
const data = {
	scale: "large", bed_count: 420, missing_total: 2,
	settings: {bed_count: 420, facility_level: "Specialized Level", has_inpatient: 1, surveillance_ratio_beds: 150},
	components: [
		{key: "committee", label: "IC Committee", requirement: "Required (≥ 150 beds)", current: "HDK-2026-01, 5 members",
		 status: "warning", status_label: "Present — missing representative: Pharmacy"},
		{key: "ic_department", label: "Infection Control Department", requirement: "Required", current: "Khoa KSNK",
		 status: "ok", status_label: "Sufficient"},
		{key: "network", label: "IC Network", requirement: "Each", current: "1/2 departments sufficient",
		 status: "missing", status_label: "Missing 1 departments"},
		{key: "surveillance", label: "Full-time Surveillance Officers", requirement: "≥ 3", current: "2 people",
		 status: "missing", status_label: "Missing 1"},
	],
	departments: [
		{department: "D1", department_name: "Hồi sức <b>", doctors: 1, nurses: 2, status: "ok", status_label: "Sufficient"},
		{department: "D2", department_name: "Nội 1", doctors: 0, nurses: 1, status: "missing", status_label: "Missing doctor"},
	],
	committee: {name: "HDK-2026-01", decision_no: "152/QĐ-BV", valid_from: "2026-01-15", valid_to: "2029-01-14",
		members: [{employee: "E1", employee_name: "BS. A", committee_role: "Chair", representing: "Functional Unit"}],
		missing_representatives: ["Pharmacy"]},
	can_edit_settings: true, can_submit_committee: true, draft_committee: "HDK-2026-02",
};
const esc = TcKsnk.esc;
"""


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


class TestKsnkScr47(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR47], [["TcKsnk"], ["TcKsnkScr47"]], DATA + code)

	def test_status_badges_always_have_text(self):
		out = self._run(
			"""
			const s = TcKsnkScr47;
			emit({ok: s.badge("ok", "Sufficient"), missing: s.badge("missing", "Missing 1"),
				warning: s.badge("warning", "Present"), na: s.badge("na", "Not applicable"),
				optional: s.badge("optional", "Not required")});
			"""
		)
		self.assertEqual(out["ok"]["cls"], "is-pass")
		self.assertEqual(out["missing"]["cls"], "is-fail")
		self.assertEqual(out["warning"]["cls"], "is-warn")
		self.assertEqual(out["na"]["cls"], "is-neutral")
		self.assertEqual(out["optional"]["cls"], "is-neutral")
		self.assertEqual(out["missing"]["label"], "Missing 1")

	def test_summary_counts_missing_components(self):
		out = self._run(
			"""emit({missing: TcKsnkScr47.summaryText(data), done: TcKsnkScr47.summaryText({missing_total: 0})});"""
		)
		self.assertEqual(out["missing"], "Missing 2 components")
		self.assertEqual(out["done"], "Required structure complete")

	def test_component_table_and_network_escape_and_text(self):
		out = self._run(
			"""emit({components: TcKsnkScr47.componentsHtml(data, esc), network: TcKsnkScr47.networkHtml(data, esc)});"""
		)
		self.assertIn("Missing 1 departments", out["components"])
		self.assertIn('class="tc-ksnk-badge is-warn"', out["components"])
		self.assertIn("Missing doctor", out["network"])
		self.assertIn("Hồi sức &lt;b&gt;", out["network"])
		self.assertNotIn("Hồi sức <b>", out["network"])
		self.assertIn("Deactivating the last member", out["network"])

	def test_committee_card_shows_members_and_warning(self):
		out = self._run(
			"""emit({html: TcKsnkScr47.committeeHtml(data, esc), none: TcKsnkScr47.committeeHtml({committee: null}, esc)});"""
		)
		self.assertIn("HDK-2026-01", out["html"])
		self.assertIn("152/QĐ-BV", out["html"])
		self.assertIn("15/01/2026", out["html"])  # ngày dd/mm/yyyy
		self.assertIn("Chair", out["html"])
		self.assertIn("Pharmacy", out["html"])
		self.assertIn("tc-ksnk-alert is-warn", out["html"])
		self.assertIn("No committee in force", out["none"])

	def test_actions_depend_on_rights_and_read_only(self):
		out = self._run(
			"""
			emit({
				full: TcKsnkScr47.actionsHtml(data, false, esc),
				readOnly: TcKsnkScr47.actionsHtml(data, true, esc),
				noDraft: TcKsnkScr47.actionsHtml(Object.assign({}, data, {draft_committee: null}), false, esc),
				settingsRo: TcKsnkScr47.settingsHtml(Object.assign({}, data, {can_edit_settings: false}), false, esc),
				settings: TcKsnkScr47.settingsHtml(data, false, esc),
			});
			"""
		)
		self.assertIn('data-action="submit-committee"', out["full"])
		self.assertIn("/app/ic-network-member/view/report", out["full"])
		self.assertNotIn('data-action="submit-committee"', out["readOnly"])
		self.assertNotIn('data-action="submit-committee"', out["noDraft"])
		self.assertIn('data-action="save-settings"', out["settings"])
		self.assertNotIn('data-action="save-settings"', out["settingsRo"])
		self.assertIn("disabled", out["settingsRo"])

	def test_block_alert_order_result_reason_action(self):
		out = self._run(
			"""emit({html: TcKsnkScr47.blockHtml({title: "Not saved", reason: "Missing Secretary", action: "Add one"}, esc)});"""
		)
		html = out["html"]
		self.assertIn('role="alert"', html)
		self.assertLess(html.index("Not saved"), html.index("Missing Secretary"))
		self.assertLess(html.index("Missing Secretary"), html.index("Add one"))

	def test_script_registers_and_uses_desk_helpers(self):
		script = _read(SCR47)
		self.assertIn('window.TcKsnkScreens["co-cau"]', script)
		self.assertIn('"tracecore.v1.ksnk_structure.status"', script)
		self.assertIn('"tracecore.v1.ksnk_structure.save_settings"', script)
		self.assertIn('"tracecore.v1.ksnk_structure.submit_committee"', script)
		self.assertNotIn("frappe.call(", script)
		self.assertNotIn("msgprint", script)  # lỗi chặn hiện inline, không hộp thoại
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", script))

	def test_css_has_warning_badge_from_tokens(self):
		css = _read("ui/page/tc_ksnk/tc_ksnk.css")
		self.assertIn(".tc-ksnk .tc-ksnk-badge.is-warn { background: var(--tc-warn-fill); }", css)
		self.assertIn(".tc-ksnk .tc-ksnk-alert.is-warn", css)
