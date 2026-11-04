"""Nhãn QR của lô vật tư/chỉ thị trên Desk (FEAT-082, A-118): form và danh sách Batch gọi hàm in chung."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

APP_PATH = frappe.get_app_path("tracecore")


def read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestBatchLabelAssets(FrappeTestCase):
	def test_batch_form_and_list_print_through_the_shared_function(self):
		self.assertIn("tracecore.codes.print_batch_labels([frm.doc.name])", read("public", "js", "batch.js"))
		self.assertIn("tracecore.codes.print_batch_labels(", read("public", "js", "batch_list.js"))
		codes = read("public", "js", "tc_codes.js")
		self.assertIn("tracecore.v1.print.batch_labels_pdf", codes)
		self.assertIn("tcPrintPdfAndTell", codes)

	def test_hooks_load_the_scripts(self):
		hooks = frappe.get_hooks()
		self.assertEqual(hooks["doctype_js"]["Batch"], ["public/js/batch.js"])
		self.assertEqual(hooks["doctype_list_js"]["Batch"], ["public/js/batch_list.js"])
