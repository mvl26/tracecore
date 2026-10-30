"""Ô quét chung trên List View (FEAT-006, FR-M9-13; A-54 D11)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.v1 import dashboard

JS_DIR = os.path.join(frappe.get_app_path("tracecore"), "public", "js")


def _read(name):
	with open(os.path.join(JS_DIR, name), encoding="utf-8") as handle:
		return handle.read()


class TestListScan(FrappeTestCase):
	def test_bundle_imports_the_list_scan(self):
		self.assertIn('import "./tc_list_scan.js";', _read("tracecore.bundle.js"))

	def test_client_doctypes_match_the_server_list(self):
		match = re.search(r"TC_SCAN_DOCTYPES = (\[[^\]]*\])", _read("tc_list_scan.js"))
		self.assertTrue(match)
		# prettier có thể xuống dòng / thêm dấu phẩy cuối: đọc từng chuỗi thay vì parse JSON
		self.assertEqual(re.findall(r"\"([^\"]+)\"", match.group(1)), list(dashboard.SCAN_DOCTYPES))

	def test_scan_opens_one_match_or_filters_the_list(self):
		script = _read("tc_list_scan.js")
		self.assertIn('"tracecore.v1.dashboard.find_in_list"', script)
		self.assertIn("tracecore.desk_get(", script)
		self.assertIn('frappe.set_route("Form"', script)
		self.assertIn("filter_area.add(", script)

	def test_slash_focuses_the_scan_box_outside_inputs(self):
		script = _read("tc_list_scan.js")
		self.assertIn('event.key === "/"', script)
		self.assertIn("isContentEditable", script)
		self.assertIn('"aria-keyshortcuts": "/"', script)
