"""Desk SCR-01 (FEAT-014 Task 6): Client Script của Instrument / Instrument Group nằm trong thư mục DocType và gọi đúng RPC.

Hành vi trên trình duyệt kiểm bằng Playwright (Task 7); ở đây kiểm phần đọc được bằng Python: script có mặt, dùng
khóa idempotent mới mỗi thao tác ghi, không chép hằng số nghiệp vụ (danh sách phương pháp, ngưỡng D5) vào JS.
"""

import os
import re

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
