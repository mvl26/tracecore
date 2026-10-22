"""Desk SCR-01 (FEAT-014 Task 6): Client Script của Instrument / Instrument Group nằm trong thư mục DocType và gọi đúng RPC.

Hành vi trên trình duyệt kiểm bằng Playwright (Task 7); ở đây kiểm phần đọc được bằng Python: script có mặt, dùng
khóa idempotent mới mỗi thao tác ghi, không chép hằng số nghiệp vụ (danh sách phương pháp, ngưỡng D5) vào JS.
"""

import json
import os
import re
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

APP_PATH = frappe.get_app_path("tracecore")
DOCTYPE_DIR = ("instrument", "doctype")


def _read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


def _form_js():
	return _read(*DOCTYPE_DIR, "instrument", "instrument.js")


class TestDeskInstrument(FrappeTestCase):
	def test_form_script_calls_rpcs_with_fresh_idempotency_key(self):
		script = _form_js()
		for method in (
			"tracecore.v1.instrument.check_code",
			"tracecore.v1.instrument.form_context",
			"tracecore.v1.instrument.giai_preview",
			"tracecore.v1.instrument_admin.init_counters",
			"tracecore.v1.instrument_admin.retire",
			"tracecore.v1.instrument_admin.assign_giai",
			"tracecore.v1.instrument_admin.record_etching",
		):
			self.assertIn(f'"{method}"', script, method)
		# ghi: một thao tác = một request (khóa X-Idempotency-Key + client_ts) của tc_codes.js; gửi lại sau lỗi
		# mạng dùng đúng request cũ
		self.assertIn("tracecore.codes.new_request(", script)
		self.assertIn("tracecore.codes.send(", script)
		self.assertIn("window.tracecore && tracecore.codes", script)
		# retire trong BOM: gọi lại với confirm=1 sau khi người dùng xác nhận
		self.assertIn("INSTRUMENT_IN_BOM", script)
		self.assertIn("confirm: 1", script)
		self.assertIn('frappe.ui.form.on("Instrument"', script)

	def test_form_script_has_no_business_constants(self):
		script = _form_js()
		methods = frappe.get_meta("Instrument Compatible Method").get_field("method").options.split("\n")
		for method in filter(None, methods):
			self.assertNotIn(f'"{method}"', script, method)
		# ngưỡng D5 (120 %, 3 lần hoãn) chỉ ở maintenance._state
		self.assertNotRegex(script, r"\b1\.2\b|\b120\b|MAX_DEFERRALS")
		# trạng thái luôn có chữ: các nhãn trạng thái bộ đếm đi qua __()
		for label in ("Not due", "Due", "Overdue"):
			self.assertIn(f'__("{label}")', script)

	def test_list_script_shows_status_and_max_cycles_as_text(self):
		script = _read(*DOCTYPE_DIR, "instrument", "instrument_list.js")
		self.assertIn('frappe.listview_settings["Instrument"]', script)
		self.assertIn("get_indicator", script)
		self.assertIn("max_cycles_status", script)
		meta = frappe.get_meta("Instrument")
		field = meta.get_field("max_cycles_status")
		self.assertTrue(field.in_list_view and field.in_standard_filter)
		self.assertTrue(meta.get_field("status").in_list_view)

	def test_group_script_exists(self):
		script = _read(*DOCTYPE_DIR, "instrument_group", "instrument_group.js")
		self.assertIn('frappe.ui.form.on("Instrument Group"', script)

	def test_no_vietnamese_literals_outside_translation(self):
		# chuỗi hiển thị viết tiếng Anh trong __(); chú thích tiếng Việt được phép
		vietnamese = re.compile(
			r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I
		)
		for name in ("instrument.js", "instrument_list.js"):
			for number, line in enumerate(_read(*DOCTYPE_DIR, "instrument", name).splitlines(), 1):
				code = line.split("//", 1)[0]
				self.assertFalse(vietnamese.search(code), f"{name}:{number}: {line}")

	def test_media_urls_rendered_only_from_site_files(self):
		# Minor 6: URL ảnh/thumbnail/IFU chỉ vào href/src khi là /private/files/ hoặc /files/ (không javascript:,
		# data:, http… ); helper tc_instr_safe_url là đường duy nhất
		script = _form_js()
		self.assertIn("function tc_instr_safe_url(", script)
		for expr in ("image.image_url", "image.thumbnail_url", "frm.doc.ifu"):
			for match in re.finditer(re.escape(expr), script):
				before = script[max(0, match.start() - 200) : match.start()]
				self.assertIn("tc_instr_safe_url(", before, f"{expr} at {match.start()}")
		node = shutil.which("node")
		if not node:
			self.skipTest("node not installed")
		source = re.search(r"function tc_instr_safe_url\(.*?\n}\n", script, re.S).group(0)
		cases = {
			"/private/files/a-thumb.jpg": "/private/files/a-thumb.jpg",
			"/files/manual.pdf": "/files/manual.pdf",
			"javascript:alert(1)": "",
			" /private/files/x.jpg": "",
			"https://evil.example/x.jpg": "",
			"//evil.example/files/x.jpg": "",
			"data:image/png;base64,AAAA": "",
			"/private/filesx/a.jpg": "",
			"/app/instrument": "",
		}
		program = source + "\nconst cases = " + json.dumps(list(cases)) + ";\n"
		program += "console.log(JSON.stringify(cases.map((c) => tc_instr_safe_url(c))));\n"
		program += "console.log(JSON.stringify([tc_instr_safe_url(null), tc_instr_safe_url(undefined), tc_instr_safe_url(5)]));\n"
		output = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
		mapped, odd = (json.loads(line) for line in output.splitlines())
		self.assertEqual(dict(zip(cases, mapped, strict=True)), cases)
		self.assertEqual(odd, ["", "", ""])

	def test_form_buttons_removed_by_name_not_cleared(self):
		# Minor 9: không xóa nút của Client Script khác (frm.clear_custom_buttons); chỉ gỡ nút script này đã thêm
		script = _form_js()
		self.assertNotIn("clear_custom_buttons", script)
		self.assertIn("remove_custom_button(", script)
		self.assertIn("perms.can_preview_giai", script)
