"""Desk SCR-31 (FEAT-032 Task 6): Client Script của Par Override và màn T4 (SCR-08).

Hành vi trên trình duyệt kiểm bằng Playwright (``tests_e2e/test_desk_par_override.py``, site dev); ở đây kiểm phần đọc
được bằng Python/Node: mọi chuỗi qua __() có dòng vi.csv, không chữ Việt/hex trong code, nút duyệt/từ chối chỉ cho
R01/R02, lỗi chặn hiện kết quả → lý do → hành động ngay trong hộp thoại, nút "Đề nghị ghi đè" của T4 đã bật.
"""

import json
import os
import re
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.test_station_page import JS_STRING, other_app_translations, vi_translations

APP_PATH = frappe.get_app_path("tracecore")
FORM_JS = os.path.join(APP_PATH, "par", "doctype", "par_override", "par_override.js")
LIST_JS = os.path.join(APP_PATH, "par", "doctype", "par_override", "par_override_list.js")
REPORT_JS = os.path.join(APP_PATH, "par", "report", "par_override_report", "par_override_report.js")
T4_JS = os.path.join(APP_PATH, "public", "js", "station_t4.js")
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


def _read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _function(script, name):
	match = re.search(rf"function {name}\(.*?\n}}\n", script, re.S)
	assert match, name
	return match.group(0)


class TestParOverrideDeskAssets(FrappeTestCase):
	def test_strings_translated_and_no_hard_coded_text_or_colour(self):
		ours, others = vi_translations(), other_app_translations()
		for path in (FORM_JS, LIST_JS, REPORT_JS):
			script = _read(path)
			strings = sorted({match[1] for match in JS_STRING.findall(script)})
			missing = [
				s for s in strings if not (ours.get(s) or ours.get(f"{s}:Par Override") or others.get(s))
			]
			self.assertFalse(missing, f"{os.path.basename(path)}: thiếu dòng vi.csv {missing}")
			for number, line in enumerate(script.splitlines(), 1):
				code = line.split("//", 1)[0]
				self.assertFalse(VIETNAMESE.search(code), f"{number}: {line}")
				self.assertNotRegex(code, r"#[0-9a-fA-F]{3,6}\b", f"{number}: {line}")

	def test_decision_dialog_asks_for_pin_reason_cycles_and_date(self):
		script = _read(FORM_JS)
		for fieldname in ("extra_cycles", "valid_until", "reason", "pin"):
			self.assertIn(f'fieldname: "{fieldname}"', script)
		self.assertIn('fieldtype: "Password"', script)
		self.assertIn("tracecore.v1.par.override.approve", script)
		self.assertIn("tracecore.v1.par.override.reject", script)
		self.assertIn('frm.add_custom_button(__("Approve")', script)
		self.assertIn('frm.add_custom_button(__("Reject")', script)

	def test_blocking_error_is_inline_result_reason_action(self):
		script = _read(FORM_JS)
		self.assertIn("alert alert-danger", script)
		for key in ("error.title", "error.reason", "error.action"):
			self.assertIn(key, script)
		self.assertNotIn("frappe.msgprint", script)
		self.assertNotIn("frappe.show_alert", script)

	def test_buttons_only_for_deciders_on_requested_drafts(self):
		node = shutil.which("node")
		if not node:
			self.skipTest("node not installed")
		source = _function(_read(FORM_JS), "tc_par_override_can_decide")
		deciders = 'const TC_PAR_OVERRIDE_DECIDERS = ["TC R01", "TC R02"];\n'
		cases = [
			({"docstatus": 0, "status": "Requested"}, ["TC R01"], True),
			({"docstatus": 0, "status": "Requested"}, ["TC R02"], True),
			({"docstatus": 0, "status": "Requested"}, ["TC R04"], False),
			({"docstatus": 0, "status": "Requested"}, ["System Manager"], False),
			({"docstatus": 1, "status": "Approved"}, ["TC R01"], False),
			({"docstatus": 1, "status": "Rejected"}, ["TC R01"], False),
		]
		program = (
			deciders
			+ source
			+ "\nconst cases = "
			+ json.dumps(cases)
			+ ";\n"
			+ "const out = cases.map(([doc, roles]) => {\n"
			+ "  global.frappe = { user: { has_role: (r) => roles.includes(r) } };\n"
			+ "  return tc_par_override_can_decide({ doc, is_new: () => false });\n"
			+ "});\nconsole.log(JSON.stringify(out));\n"
		)
		output = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
		self.assertEqual(json.loads(output), [expected for *_args, expected in cases])

	def test_list_indicator_has_text_for_every_status(self):
		script = _read(LIST_JS)
		for status in ("Requested", "Approved", "Rejected", "Expired", "Cancelled"):
			self.assertIn(f"{status}:", script)
		self.assertIn('__(doc.status, null, "Par Override")', script)


class TestT4OverrideButton(FrappeTestCase):
	def test_request_override_button_is_enabled_and_wired(self):
		script = _read(T4_JS)
		self.assertNotIn("Available from FEAT-032", script)
		self.assertIn('data-action="request-override"', script)
		self.assertIn('"request-override": () => this.requestOverride()', script)
		self.assertIn("tracecore.v1.par.override.request", script)
		for code in ("PAR_EXCEEDED", "SET_END_OF_LIFE"):
			self.assertIn(f'"{code}"', script)

	def test_request_dialog_requires_a_reason_and_confirms_with_override_name(self):
		script = _read(T4_JS)
		body = script[script.index("requestOverride() {") :]
		body = body[: body.index("voidPack() {")]
		self.assertIn("required: true", body)
		self.assertIn("this.station.station", body)
		self.assertIn("Override request {0} sent", body)

	def test_t4_par_notes_cover_override_and_instruments(self):
		script = _read(T4_JS)
		self.assertIn("parNoteHtml(par)", script)
		self.assertIn("Override {0}: {1} more cycle(s) allowed until {2}", script)
		self.assertIn("{0} ({1}) reached its cycle limit", script)
		self.assertIn("{0} cycles used · limit not defined", script)
