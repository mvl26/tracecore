"""Màn SCR-56 Ca NKBV & kỳ báo cáo, SCR-58 tỷ suất NKBV trong Page tc-ksnk (FEAT-063; UC-48; FR-M13-05.1, 06, 10.1,
10.2, 11, 15; BRU-HAI-006; A-131, A-144 g)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import bru
from tracecore.ui import ksnk

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR56 = "public/js/ksnk/scr_56_ca_nkbv.js"
SCR58 = "public/js/ksnk/scr_58_bao_cao_nkbv.js"
FORM = "hai_surveillance/doctype/hai_case/hai_case.js"
HEX_OR_PX = re.compile(r"#[0-9a-fA-F]{3,6}\b|\d+px")

DATA = """
const data = {
	ok: true, current_period: "2026-11", current_locked: 0, can_decide: true, can_reveal: true, can_lock: true,
	cases: [
		{name: "CA-2026-00087", patient_code_masked: "***4821", department_name: "Hồi sức <b>", def_code: "VAP",
		 status: "Suspected", docstatus: 0},
		{name: "CA-2026-00084", patient_code_masked: "***3318", department_name: "Nội 2", def_code: "CAUTI",
		 status: "Excluded", docstatus: 1},
	],
	periods: [
		{name: "KY-2026-11", month: "2026-11", locked: 0, missing_wards: 1, unlock_count: 0},
		{name: "KY-2026-09", month: "2026-09", locked: 1, locked_by_name: "Nguyễn Thị Hạnh", locked_on: "2026-10-06 08:00:00",
		 unlock_count: 1, unlock_reason: "bổ sung ca NKVM"},
	],
};
const detail = {
	name: "CA-2026-00087", status: "Suspected", docstatus: 0, patient_code_masked: "***4821", birth_year: 1958,
	sex: "Male", department_name: "Hồi sức", admission_at: "2026-10-27 14:20:00", onset_date: "2026-11-02",
	case_definition: "DN-VAP-V1", device_episode: "DTB-2026-00412",
	episode: {device_type: "Ventilator", device_days: 4}, isolates: [{isolate: "VS-2026-01204", organism: "kpn",
	mdro_flags: "CRE"}], time_check: "Met", time_check_note: "Device in place 4 days before onset.",
	reporting_period: "2026-11", period_locked: false,
};
const report = {
	ok: true, period: "2026-10", locked: 1,
	months: [{month: "2026-11", locked: 0}, {month: "2026-10", locked: 1}],
	hospital: {hai: 3.1, vap: 4.878, clabsi: null, cauti: 2.2},
	departments: [
		{department: "D1", department_name: "Hồi sức tích cực", patient_days: 552, cases: 5, hai: 9.0579, vap: 9.6,
		 clabsi: 2.9, cauti: null, vent_utilization: 41.5},
	],
	trend: [{month: "2026-09", cases: 2, patient_days: 1240, value: 1.6129}, {month: "2026-10", cases: 0,
		patient_days: 0, value: null}],
};
const esc = TcKsnk.esc;
"""


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


class TestKsnkScr56(FrappeTestCase):
	def _run(self, files, names, code):
		return run_js(self, [SHELL, *files], [["TcKsnk"], *names], DATA + code)

	def test_registered_in_page_registry(self):
		screens = {screen["slug"]: screen for screen in ksnk.SCREENS}
		self.assertEqual(screens["ca-nkbv"]["scr"], "SCR-56")
		self.assertNotIn("TC R13", screens["ca-nkbv"]["roles"])  # FR-M13-15.3
		self.assertIn("TC R13", screens["bao-cao-nkbv"]["roles"])
		self.assertEqual(screens["bao-cao-nkbv"]["group"], "hai")

	def test_list_masks_code_and_badges_have_text(self):
		out = self._run(
			[SCR56],
			[["TcKsnkScr56"]],
			"""emit({page: TcKsnkScr56.pageHtml(data, esc, null),
				empty: TcKsnkScr56.listHtml([], esc, null)});""",
		)
		page = out["page"]
		self.assertIn("***4821", page)
		self.assertIn("Hồi sức &lt;b&gt;", page)
		self.assertIn('tc-ksnk-badge is-warn">Suspected', page)
		self.assertIn("KY-2026-11", page)
		self.assertIn('data-action="lock" data-month="2026-11"', page)
		self.assertIn('data-action="unlock" data-month="2026-09"', page)
		self.assertIn("1 department(s) without a full census", page)
		self.assertIn("/app/hai-case/new", out["empty"])
		self.assertIn("No HAI cases yet.", out["empty"])

	def test_detail_actions_by_role_and_lock(self):
		out = self._run(
			[SCR56],
			[["TcKsnkScr56"]],
			"""
			const s = TcKsnkScr56;
			emit({
				open: s.detailHtml(detail, data, esc),
				viewer: s.detailHtml(detail, Object.assign({}, data, {can_decide: false, can_reveal: false}), esc),
				locked: s.detailHtml(Object.assign({}, detail, {period_locked: true}), data, esc),
				notmet: s.detailHtml(Object.assign({}, detail, {time_check: "Not met"}), data, esc),
			});
			""",
		)
		self.assertIn('data-action="confirm"', out["open"])
		self.assertIn('data-action="exclude"', out["open"])
		self.assertIn('data-action="reveal"', out["open"])
		self.assertIn("DN-VAP-V1", out["open"])
		self.assertIn("CRE", out["open"])
		self.assertIn("Time check by DN-VAP-V1: met.", out["open"])
		self.assertNotIn('data-action="confirm"', out["viewer"])  # FR-M13-05.1
		self.assertNotIn('data-action="reveal"', out["viewer"])
		self.assertNotIn('data-action="confirm"', out["locked"])
		self.assertIn("is locked", out["locked"])
		self.assertIn("is-warn", out["notmet"])
		self.assertIn("enter an exception reason", out["notmet"])

	@bru("BRU-HAI-006")
	def test_report_shows_not_calculated_never_zero(self):
		out = self._run(
			[SCR58],
			[["TcKsnkScr58"]],
			"""emit({page: TcKsnkScr58.pageHtml(report, esc), vap: TcKsnkScr58.num(4.878),
				big: TcKsnkScr58.int(1240), none: TcKsnkScr58.num(null)});""",
		)
		self.assertEqual(out["vap"], "4,9")  # FR-M13-10.1
		self.assertEqual(out["big"], "1.240")
		self.assertEqual(out["none"], "Not calculated")  # FR-M13-10.2
		page = out["page"]
		self.assertIn("Not calculated", page)
		self.assertIn("9,1", page)
		self.assertIn("Month 10/2026 (locked)", page)
		self.assertIn('style="width: 100%"', page)

	def test_states_tokens_and_strings(self):
		for path in (SCR56, SCR58, FORM):
			code = _read(path)
			self.assertIsNone(HEX_OR_PX.search(re.sub(r"//.*", "", code)), path)
		for path in (SCR56, SCR58):
			code = _read(path)
			self.assertIn('ctx.state("loading")', code)
			self.assertIn('ctx.state("error"', code)
		self.assertIn("No HAI cases yet.", _read(SCR56))
		self.assertIn("No census or HAI case in this month.", _read(SCR58))
		self.assertIn("tracecore.v1.hai_case.decide", _read(FORM))
		self.assertIn("tracecore.v1.patient_code.reveal", _read(FORM))
