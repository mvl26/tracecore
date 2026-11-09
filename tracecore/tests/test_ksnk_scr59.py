"""Màn SCR-59 Vi sinh & đa kháng trong Page tc-ksnk (FEAT-067 AC-1, AC-6, AC-11, AC-12, AC-15; A-131, A-136)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR59 = "public/js/ksnk/scr_59_vi_sinh.js"

DATA = """
const data = {
	ok: true, year: 2026, quarter: 3, can_read_isolates: true, can_import: true, can_manual: true,
	import_kind: "microbiology", profiles: [{name: "WHONET - Khoa Vi sinh", file_format: "CSV"}],
	catalog: [{name: "kpn", organism_name: "Klebsiella pneumoniae"}],
	departments: [{name: "D1", department_name: "Hồi sức"}],
	pending: {count: 2, first_sent: "2026-08-12 09:12:00"},
	recent: [
		{name: "VS-2026-01204", lab_sample_id: "L1", patient_code_masked: "***4821", department_name: "Hồi sức <b>",
		 specimen_type: "Blood", organism: "kpn", organism_name: "Klebsiella pneumoniae", is_mdro: 1,
		 mdro_flags: "CRE", is_first_isolate: 1, history: ["MRSA"]},
		{name: "VS-2026-01205", lab_sample_id: "L2", patient_code_masked: "***1111", department_name: "Nội",
		 organism: "eco", organism_name: "Escherichia coli", is_mdro: 0, mdro_flags: null, is_first_isolate: 0,
		 history: []},
	],
	organisms: [{organism: "kpn", organism_name: "Klebsiella pneumoniae", first_isolates: 84}],
	antibiogram: {organism: "kpn", organism_name: "Klebsiella pneumoniae", first_isolates: 84, threshold: 30,
		rows: [{antibiotic: "MEM", antibiotic_name: "Meropenem", tested: 84, s_pct: 58, i_pct: 4, r_pct: 38,
			small_sample: false},
			{antibiotic: "COL", antibiotic_name: "Colistin", tested: 12, s_pct: 96.4, i_pct: 0, r_pct: 3.6,
			small_sample: true}]},
	rules: {approved: 3, draft: 1},
	report: "/app/query-report/Antimicrobial Resistance by Quarter",
};
const check = {total: 1248, valid: 1231, existing: new Array(12).fill("x"),
	issues: [{row: 7, field: "organism", code: "ORGANISM_NOT_FOUND", reason: "Organism code xyz is not in the catalog."}],
	warnings: ["Column(s) LAST_NAME were ignored: patient names are not stored."]};
const esc = TcKsnk.esc;
"""


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


class TestKsnkScr59(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR59], [["TcKsnk"], ["TcKsnkScr59"]], DATA + code)

	def test_import_card_shows_steps_counts_errors_and_save_button(self):
		out = self._run(
			"""
			const s = TcKsnkScr59;
			emit({
				fresh: s.importHtml(data, {profile: data.profiles[0].name}, esc),
				checked: s.importHtml(data, {profile: data.profiles[0].name, file_url: "/private/files/a.csv",
					file_name: "a.csv", check}, esc),
				none: s.importHtml(Object.assign({}, data, {can_import: false}), {}, esc),
			});
			"""
		)
		self.assertIn('aria-current="step"', out["fresh"])
		self.assertIn('data-action="check" disabled', out["fresh"])
		self.assertIn("Manual entry when there is no file", out["fresh"])
		checked = out["checked"]
		for text in (
			"1248",
			"1231",
			"Duplicates (lab sample ID, organism)",
			'is-fail"',
			"Save 1231 valid rows",
		):
			self.assertIn(text, checked)
		self.assertIn('role="alert"', checked)
		self.assertIn("LAST_NAME were ignored", checked)
		self.assertLess(
			checked.index("with errors are not saved"), checked.index("row number and the reason")
		)
		self.assertEqual(out["none"], "")

	def test_recent_isolates_mask_and_label_in_text(self):
		out = self._run(
			"""emit({html: TcKsnkScr59.recentHtml(data.recent, esc), empty: TcKsnkScr59.recentHtml([], esc)});"""
		)
		html = out["html"]
		self.assertIn("***4821", html)
		self.assertIn('tc-ksnk-badge is-fail">CRE', html)
		self.assertIn("Previously carried MRSA", html)
		self.assertIn("No (repeat)", html)
		self.assertIn("Hồi sức &lt;b&gt;", html)
		self.assertNotIn("Hồi sức <b>", html)
		self.assertIn("No isolate recorded", out["empty"])

	def test_pending_banner_and_rules_note(self):
		out = self._run(
			"""emit({pending: TcKsnkScr59.pendingHtml(data.pending, esc), none: TcKsnkScr59.pendingHtml({count: 0}, esc),
				rules: TcKsnkScr59.rulesHtml(data, esc)});"""
		)
		self.assertIn("2 new multidrug-resistant", out["pending"])
		self.assertIn("09:12 12/08/2026", out["pending"])
		self.assertEqual(out["none"], "")
		self.assertIn("1 draft(s)", out["rules"])
		self.assertIn("/app/mdro-rule", out["rules"])

	def test_antibiogram_uses_comma_decimals_and_small_sample_text(self):
		out = self._run("""emit({html: TcKsnkScr59.antibiogramHtml(data, esc)});""")
		html = out["html"]
		self.assertIn("38,0 %", html)
		self.assertIn("96,4 %", html)
		self.assertIn("Small sample (n &lt; 30)", html)
		self.assertIn("n = 84 first isolates", html)
		self.assertIn("year=2026&amp;quarter=3", html)

	def test_manual_form_and_preview_need_confirmation(self):
		out = self._run(
			"""
			emit({
				form: TcKsnkScr59.manualFormHtml(data, esc),
				preview: TcKsnkScr59.previewHtml({lab_sample_id: "M1", organism_name: "K. pneumoniae",
					patient_code_masked: "***7777", department_name: "Hồi sức", collected_on: "2026-08-12",
					susceptibility: [{antibiotic: "MEM", result: "R", mic: ">8"}], mdro_labels: ["CRE"]}, esc),
			});
			"""
		)
		self.assertIn('data-manual="patient_code"', out["form"])
		self.assertIn('data-action="preview"', out["form"])
		self.assertNotIn("patient_name", out["form"])
		self.assertIn('data-action="confirm"', out["preview"])
		self.assertIn("***7777", out["preview"])
		self.assertIn("12/08/2026", out["preview"])

	def test_block_alert_order_result_reason_action(self):
		out = self._run(
			"""emit({html: TcKsnkScr59.blockHtml({title: "Not saved", reason: "Bad", action: "Fix"}, esc)});"""
		)
		self.assertLess(out["html"].index("Not saved"), out["html"].index("Bad"))
		self.assertLess(out["html"].index("Bad"), out["html"].index("Fix"))

	def test_script_registers_and_uses_rpc_helpers(self):
		script = _read(SCR59)
		self.assertIn('window.TcKsnkScreens["vi-sinh"]', script)
		for method in (
			"micro.overview",
			"micro.manual_preview",
			"micro.manual_entry",
			"imports.check",
			"imports.run",
		):
			self.assertIn(f'"tracecore.v1.{method}"', script)
		self.assertNotIn("frappe.call(", script)
		self.assertNotIn("msgprint", script)
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", script))
