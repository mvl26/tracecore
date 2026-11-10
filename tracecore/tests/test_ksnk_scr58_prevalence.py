"""SCR-58 khối điều tra cắt ngang (FEAT-072 AC-8, AC-10, AC-12; FR-M13-14; UC-50 bước 5, 6, E2; BRU-RPT-001; A-149)."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR58 = "public/js/ksnk/scr_58_bao_cao_nkbv.js"

DATA = """
const p = {
	ok: true, date: "2026-10-15", dates: ["2026-10-15", "2026-07-01"], template: "MP-CAT-NGANG-V1", can_record: true,
	departments: [
		{department: "D1", department_name: "Hồi sức <b>", surveyed: 18, hai: 4, antibiotic: 16, rate: 22.2,
		 antibiotic_rate: 88.9},
	],
	hospital: {surveyed: 18, hai: 4, antibiotic: 16, rate: 22.2, antibiotic_rate: 88.9},
};
const ctx = {departments: [{name: "D1", department_name: "Hồi sức"}], filters: {}};
const esc = TcKsnk.esc;
"""


class TestKsnkScr58Prevalence(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR58], [["TcKsnk"], ["TcKsnkPps"]], DATA + code)

	def test_table_by_department_with_hospital_total(self):
		out = self._run(
			"""emit({html: TcKsnkPps.cardHtml(p, ctx, esc),
				empty: TcKsnkPps.tableHtml({departments: [], hospital: {surveyed: 0, rate: null}}, esc),
				na: TcKsnkPps.pct(null)});"""
		)
		html = out["html"]
		self.assertIn("Hồi sức &lt;b&gt;", html)
		self.assertIn("22,2 %", html)
		self.assertIn("88,9 %", html)
		self.assertIn('class="is-total"', html)
		self.assertIn("15/10/2026", html)
		self.assertIn("never by name", html)
		self.assertIn("No patient surveyed", out["empty"])
		self.assertEqual(out["na"], "Not calculated")

	def test_record_form_only_for_recorders_and_needs_template(self):
		out = self._run(
			"""emit({form: TcKsnkPps.formHtml(p, ctx, esc),
				ro: TcKsnkPps.formHtml(Object.assign({}, p, {can_record: false}), ctx, esc),
				noTpl: TcKsnkPps.formHtml(Object.assign({}, p, {template: null}), ctx, esc)});"""
		)
		self.assertIn('data-pps="record"', out["form"])
		self.assertIn("Patient code (no name)", out["form"])
		self.assertEqual(out["ro"], "")
		self.assertIn("No approved point prevalence survey template", out["noTpl"])
		self.assertNotIn('data-pps="record"', out["noTpl"])

	def test_candidates_show_masked_code_and_devices(self):
		out = self._run(
			"""emit({html: TcKsnkPps.candidatesHtml([{patient_code_masked: "***0021",
				episodes: [{name: "DTB-2026-00001", device_type: "Ventilator"}, {name: "DTB-2026-00002",
				device_type: "Urinary Catheter"}]}], esc), none: TcKsnkPps.candidatesHtml([], esc)});"""
		)
		self.assertIn("***0021", out["html"])
		self.assertIn('data-episode="DTB-2026-00001"', out["html"])
		self.assertIn("Ventilator, Urinary Catheter", out["html"])
		self.assertIn("enter other patients by code", out["none"])

	def test_block_alert_order(self):
		out = self._run(
			"""emit({html: TcKsnkPps.blockHtml({title: "Patient already surveyed", reason: "R", action: "A"}, esc)});"""
		)
		html = out["html"]
		self.assertIn('role="alert"', html)
		self.assertLess(html.index("Patient already surveyed"), html.index("<div>R</div>"))
		self.assertLess(html.index("<div>R</div>"), html.index("<div>A</div>"))
