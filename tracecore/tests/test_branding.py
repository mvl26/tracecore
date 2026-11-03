"""Tên và logo của bệnh viện trên thanh điều hướng Desk: lấy theo Website Settings của từng site, không ghi cứng."""

from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks
from tracecore.ui import branding

APP = Path(__file__).resolve().parents[1]


class TestBranding(FrappeTestCase):
	def setUp(self):
		self.original = frappe.db.get_single_value("Website Settings", "app_name")
		self.addCleanup(self._set_app_name, self.original)

	def _set_app_name(self, value):
		frappe.db.set_single_value("Website Settings", "app_name", value)
		frappe.clear_cache()

	def test_brand_is_the_app_name_of_the_site(self):
		self._set_app_name("Bệnh viện đa khoa Đức Giang")
		boot = frappe._dict()
		branding.extend_bootinfo(boot)
		self.assertEqual(boot.tc_brand, "Bệnh viện đa khoa Đức Giang")

	def test_brand_falls_back_to_tracecore(self):
		for value in (None, "", "Frappe"):
			with self.subTest(value=value):
				self._set_app_name(value)
				boot = frappe._dict()
				branding.extend_bootinfo(boot)
				self.assertEqual(boot.tc_brand, "TraceCore")

	def test_hook_and_navbar_use_the_brand(self):
		self.assertIn("tracecore.ui.branding.extend_bootinfo", hooks.extend_bootinfo)
		self.assertIn("tracecore.ui.page_cache.extend_bootinfo", hooks.extend_bootinfo)
		source = (APP / "public" / "js" / "tc_launcher.js").read_text(encoding="utf-8")
		self.assertIn("frappe.boot.tc_brand", source)
		self.assertNotIn(">TraceCore</span>", source)
