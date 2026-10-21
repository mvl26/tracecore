"""Desk SCR-33 (FEAT-005 Task 5): script dùng chung in nhãn QR và nút cấp mã cuộn trên form Item được đăng ký qua hook."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

APP_PATH = frappe.get_app_path("tracecore")


def _read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestDeskCodes(FrappeTestCase):
	def test_hooks_register_item_script_and_include_js(self):
		# form Item (ERPNext) nhận nút "Cấp mã cuộn" qua doctype_js, không sửa app erpnext
		self.assertIn("public/js/item.js", frappe.get_hooks("doctype_js").get("Item", []))
		self.assertIn("tracecore.codes.issue_rolls_dialog(frm)", _read("public", "js", "item.js"))
		# tracecore.codes.print_dialog nạp sẵn trên mọi trang Desk (bundle có hash, như tracecore.bundle.css)
		self.assertEqual(frappe.get_hooks("app_include_js", app_name="tracecore"), ["tracecore.bundle.js"])
		self.assertIn('import "./tc_codes.js";', _read("public", "js", "tracecore.bundle.js"))
		helper = _read("public", "js", "tc_codes.js")
		self.assertIn("tracecore.codes.print_dialog", helper)
		self.assertIn("tracecore.v1.print.object_label", helper)
		self.assertIn("tracecore.v1.print.object_preview", helper)
		self.assertIn("tracecore.v1.codes.issue_rolls", helper)
		self.assertIn("X-Idempotency-Key", helper)
