"""Desk SCR-30 (FEAT-031 Task 3): Client Script của Par Level.

Hành vi trên trình duyệt kiểm bằng Playwright (``tests_e2e/test_desk_par.py``, site dev); ở đây kiểm phần đọc được
bằng Python: mọi chuỗi qua __() có dòng vi.csv, không chữ Việt/hex trong code, trạng thái luôn có chữ, hộp xác nhận
trước khi lưu cơ số ≤ chu trình đã dùng (FR-M8-01.4), lý do bắt buộc khi đổi cơ số (FR-M8-01.3), bảng lịch sử chỉ đọc.
"""

import json
import os
import re
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.test_station_page import JS_STRING, vi_translations

APP_PATH = frappe.get_app_path("tracecore")
FORM_JS = os.path.join(APP_PATH, "par", "doctype", "par_level", "par_level.js")
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


def _script():
	with open(FORM_JS, encoding="utf-8") as handle:
		return handle.read()


def _function(script, name):
	match = re.search(rf"function {name}\(.*?\n}}\n", script, re.S)
	assert match, name
	return match.group(0)


class TestParLevelDeskAssets(FrappeTestCase):
	def test_strings_translated_and_no_hard_coded_text_or_colour(self):
		script = _script()
		ours = vi_translations()
		strings = sorted({match[1] for match in JS_STRING.findall(script)})
		self.assertTrue(strings)
		missing = [s for s in strings if not ours.get(s) and not ours.get(f"{s}:Par Level")]
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")
		for number, line in enumerate(script.splitlines(), 1):
			code = line.split("//", 1)[0]
			self.assertFalse(VIETNAMESE.search(code), f"{number}: {line}")
			self.assertNotRegex(code, r"#[0-9a-fA-F]{3,6}\b", f"{number}: {line}")

	def test_status_badge_always_has_text(self):
		script = _script()
		self.assertIn('__("Defined")', script)
		self.assertIn('__("Undefined")', script)
		self.assertIn('__("Used {0} / Limit {1}", [', script)

	def test_confirm_dialog_before_saving_cap_not_above_used(self):
		# FR-M8-01.4: hỏi xác nhận trước khi lưu; đồng ý → tick confirm_below_used rồi lưu lại (server vẫn kiểm)
		script = _script()
		self.assertIn("validate(frm)", script)
		self.assertIn("frappe.validated = false", script)
		self.assertIn("frappe.confirm(", script)
		self.assertIn('frm.set_value("confirm_below_used", 1)', script)
		node = shutil.which("node")
		if not node:
			self.skipTest("node not installed")
		source = _function(script, "tc_par_needs_confirm")
		cases = [
			({"par_kind": "Reprocessing", "max_cycles": 40}, 40, True),
			({"par_kind": "Reprocessing", "max_cycles": 10}, 40, True),
			({"par_kind": "Reprocessing", "max_cycles": 41}, 40, False),
			({"par_kind": "Reprocessing", "max_cycles": 0}, 40, False),  # Chưa xác định: không hỏi
			({"par_kind": "Reprocessing", "max_cycles": 10}, None, False),  # chưa có bộ đếm (G4)
			({"par_kind": "Reprocessing", "max_cycles": 10, "confirm_below_used": 1}, 40, False),
			({"par_kind": "Department Stock", "max_cycles": 10}, 40, False),
		]
		program = source + "\nconst cases = " + json.dumps([[doc, used] for doc, used, _ in cases]) + ";\n"
		program += "console.log(JSON.stringify(cases.map(([d, u]) => tc_par_needs_confirm(d, u))));\n"
		output = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
		self.assertEqual(json.loads(output), [expected for *_args, expected in cases])

	def test_reason_required_on_form_when_cap_changes(self):
		# FR-M8-01.3: đổi max_cycles / min_qty / max_qty trên bản đã lưu → trường lý do bắt buộc (server vẫn kiểm)
		script = _script()
		self.assertIn('frm.toggle_reqd("reason"', script)
		for field in ("max_cycles", "min_qty", "max_qty"):
			self.assertIn(f'"{field}"', script)

	def test_meta_history_read_only_and_ifu_hint(self):
		meta = frappe.get_meta("Par Level")
		self.assertTrue(meta.get_field("history").read_only)
		self.assertIn("never taken from the IFU", meta.get_field("max_cycles").description)
