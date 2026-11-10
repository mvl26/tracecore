"""Màn SCR-57 Giám sát NKVM và khối NKVM / xuất báo cáo của SCR-58 trong Page tc-ksnk (FEAT-064; UC-49; FR-M13-07..09,
12; BRU-HAI-005, BRU-RPT-002; A-131, A-147 k)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import bru
from tracecore.ui import ksnk

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR57 = "public/js/ksnk/scr_57_nkvm.js"
SCR58 = "public/js/ksnk/scr_58_bao_cao_nkbv.js"
HEX_OR_PX = re.compile(r"#[0-9a-fA-F]{3,6}\b|\d+px")

DATA = """
const detail = {
	name: "PT-2026-00391", outcome: "Under Surveillance", patient_code_masked: "***6612", birth_year: 1961,
	sex: "Female", department: "D1", procedure_group: "HPRO", group_name: "Thay khớp háng", surgery_date: "2026-10-28",
	asa_score: 3, wound_class: "Clean", duration_min: 150, has_implant: 0, nnis_index: "2",
	nnis_note: "ASA ≥ 3 (1) + Contaminated or Dirty wound (0) + duration > T 120 min (1)", window_days: 90,
	window_end: "2027-01-26", prophylaxis_given: 1, prophylaxis_agent: "Cefazolin 2 g",
	prophylaxis_minutes_before_incision: "45", prophylaxis_timing: "On time", discharge_date: "2026-11-02",
	data_complete: 1, period_locked: false, window_over: false, hai_case: null,
	followups: [
		{name: "r1", due_date: "2026-11-04", method: "Phone", is_final: 0, done_on: "2026-11-04", result: "SSI suspected"},
		{name: "r2", due_date: "2026-11-27", method: "Phone", is_final: 0, done_on: null, result: null},
		{name: "r3", due_date: "2027-01-26", method: "Revisit", is_final: 1, done_on: null, result: null},
	],
};
const data = {
	ok: true, threshold: 60,
	kpis: {under_surveillance: 389, ssi_month: "2026-10", ssi_rate: 1.8, on_time_rate: 91, due_today: 6},
	groups: [{name: "HPRO", group_name: "Thay khớp háng", t_time_minutes: 120, has_implant: 1}],
	recent: [
		{name: "PT-2026-00391", group_name: "Thay khớp háng <b>", nnis_index: "2", prophylaxis_timing: "On time",
		 outcome: "Under Surveillance"},
		{name: "PT-2026-00388", group_name: "Cắt ruột thừa", nnis_index: "", prophylaxis_timing: "Late", outcome: "SSI"},
	],
	due: [{name: "PT-2026-00391", patient_code_masked: "***6612", group_name: "Thay khớp háng", due_date: "2026-11-04",
		method: "Phone"}],
	definitions: [{def_code: "SSI-SUP", title: "NKVM nông"}],
	detail: null,
};
const summary = {
	period_from: "2026-10", period_to: "2026-10",
	totals: {surgeries: 2, ssi_rate: 50, prophylaxis_rate: 100, on_time_rate: null},
	groups: [{group_name: "Cắt ruột thừa", surgeries: 2, ssi: 1, ssi_rate: 50, nnis_0: 1, ssi_nnis_0: 0, nnis_1: 0,
		ssi_nnis_1: 0, nnis_2: 1, ssi_nnis_2: 1, nnis_3: 0, ssi_nnis_3: 0, prophylaxis_rate: 100, on_time_rate: null}],
};
const kinds = [{key: "ssi_cases", label: "NKVM (từng ca)", profiles: [{name: "Sở Y tế", file_format: "CSV"}]}];
const esc = TcKsnk.esc;
const depts = [{name: "D1", department_name: "Chấn thương chỉnh hình"}];
"""


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


class TestKsnkScr57(FrappeTestCase):
	def _run(self, code):
		return run_js(
			self, [SHELL, SCR57, SCR58], [["TcKsnk"], ["TcKsnkScr57"], ["TcKsnkScr58"]], DATA + code
		)

	def test_registered_for_r01_r11_only(self):
		screens = {screen["slug"]: screen for screen in ksnk.SCREENS}
		self.assertEqual((screens["nkvm"]["scr"], screens["nkvm"]["group"]), ("SCR-57", "hai"))
		self.assertEqual(set(screens["nkvm"]["roles"]), {"TC R01", "TC R11", "System Manager"})

	@bru("BRU-HAI-005")
	def test_new_registration_and_kpis(self):
		out = self._run("emit({page: TcKsnkScr57.pageHtml(data, depts, esc)});")
		page = out["page"]
		self.assertIn("389", page)
		self.assertIn("SSI rate (10/2026)", page)
		self.assertIn("1,8 %", page)
		self.assertIn('data-field="patient_code"', page)
		self.assertIn("Thay khớp háng — T 120 (implant)", page)
		self.assertIn("On time: 0 to 60 min before incision", page)
		self.assertIn("Thay khớp háng &lt;b&gt;", page)
		self.assertIn('tc-ksnk-badge is-fail">SSI', page)
		self.assertIn("***6612", page)  # lần theo dõi đến hạn: chỉ mã che
		self.assertIn('data-action="import"', page)
		self.assertNotIn('data-action="new"', page)

	def test_existing_surgery_detail(self):
		out = self._run(
			"""emit({page: TcKsnkScr57.pageHtml(Object.assign({}, data, {detail}), depts, esc),
				locked: TcKsnkScr57.formHtml(data, Object.assign({}, detail, {period_locked: true}), depts, esc),
				inpatient: TcKsnkScr57.followupsHtml(Object.assign({}, detail, {followups: [], window_over: true,
					discharge_date: "2027-03-01"}), data, esc)});"""
		)
		page = out["page"]
		self.assertIn('placeholder="***6612"', page)  # mã cũ không bao giờ đưa ra trình duyệt
		self.assertIn("<b>2</b>", page)
		self.assertIn("26/01/2027", page)
		self.assertIn("45 min before incision", page)
		self.assertIn('tc-ksnk-badge is-pass">On time', page)
		self.assertIn('data-action="record" data-row="r2"', page)
		self.assertNotIn('data-row="r1"', page)
		self.assertIn('data-action="case"', page)  # nghi ngờ NKVM, chưa có ca
		self.assertIn("(last)", page)
		self.assertIn('data-action="new"', page)
		self.assertIn("is locked", out["locked"])
		self.assertIn('data-action="close-nossi"', out["inpatient"])
		self.assertIn("follow up as an inpatient", out["inpatient"])

	def test_followup_badges_have_text(self):
		out = self._run(
			"""const b = (row, today) => TcKsnkScr57.followupBadge(row, esc, today);
			emit({today: b({due_date: "2026-11-10"}, "2026-11-10"), late: b({due_date: "2026-11-01"}, "2026-11-10"),
				later: b({due_date: "2026-12-01"}, "2026-11-10"),
				lost: TcKsnkScr57.outcomeBadge("Lost to Follow-up", esc)});"""
		)
		self.assertIn("Due today", out["today"])
		self.assertIn("Overdue", out["late"])
		self.assertIn("Not yet due", out["later"])
		self.assertIn("Lost to Follow-up", out["lost"])

	@bru("BRU-RPT-002")
	def test_scr58_ssi_block_and_export(self):
		out = self._run(
			"""emit({ssi: TcKsnkScr58.ssiHtml(summary, esc), exp: TcKsnkScr58.exportHtml(kinds, summary, esc),
				none: TcKsnkScr58.exportHtml([], summary, esc)});"""
		)
		self.assertIn("1/1", out["ssi"])  # NNIS 2: 1 ca NKVM / 1 ca mổ
		self.assertIn("50,0 %", out["ssi"])
		self.assertIn("Not calculated", out["ssi"])
		self.assertIn("Sở Y tế (CSV)", out["exp"])
		self.assertIn("masked patient code", out["exp"])
		self.assertEqual(out["none"], "")  # R10/R13 không xuất

	def test_tokens_states_and_strings(self):
		for path in (SCR57, SCR58):
			code = _read(path)
			self.assertIsNone(HEX_OR_PX.search(re.sub(r"//.*", "", code)), path)
		code = _read(SCR57)
		self.assertIn('ctx.state("loading")', code)
		self.assertIn('ctx.state("error"', code)
		self.assertIn("No surgery under surveillance yet.", code)
		self.assertIn("tracecore.v1.ssi.", code)
