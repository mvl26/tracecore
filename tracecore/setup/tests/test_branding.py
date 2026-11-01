"""Thương hiệu trang đăng nhập (#1830 G-01)."""

import frappe

from tracecore.setup import branding
from tracecore.tests.utils import IsolatedTestCase


class TestLoginBranding(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value("Website Settings", "app_name", "")

	def test_sets_the_name_when_it_is_still_the_default(self):
		self.assertTrue(branding.apply_login_branding()["changed"])
		self.assertEqual(frappe.db.get_single_value("Website Settings", "app_name"), "TraceCore")

	def test_keeps_a_name_another_app_has_set(self):
		frappe.db.set_single_value("Website Settings", "app_name", "Miyano")
		self.assertFalse(branding.apply_login_branding()["changed"])
		self.assertEqual(frappe.db.get_single_value("Website Settings", "app_name"), "Miyano")

	def test_migrate_does_not_rebrand_by_itself(self):
		hooks = frappe.get_hooks("after_migrate") + frappe.get_hooks("after_install")
		self.assertFalse([hook for hook in hooks if "branding" in hook])
