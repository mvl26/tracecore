"""Role-space access is separate from document permissions (Admin UI A-35)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAdminUI(FrappeTestCase):

	def test_guest_is_denied(self):
		from tracecore.v1.admin_ui import bootstrap

		with patch("frappe.session", frappe._dict(user="Guest")):
			with self.assertRaises(frappe.PermissionError):
				bootstrap()

	def test_operator_only_receives_assigned_role(self):
		from tracecore.v1.admin_ui import available_roles

		with (
			patch("frappe.session", frappe._dict(user="operator@example.test")),
			patch("frappe.get_roles", return_value=["TC R03", "System Manager"]),
		):
			self.assertEqual(available_roles(), ["R03"])

	def test_administrator_has_ten_spaces(self):
		from tracecore.v1.admin_ui import available_roles

		with patch("frappe.session", frappe._dict(user="Administrator")):
			self.assertEqual(available_roles(), [f"R{i:02d}" for i in range(1, 11)])

	def test_role_cannot_be_forged_in_list_request(self):
		from tracecore.v1.admin_ui import records

		with (
			patch("frappe.session", frappe._dict(user="operator@example.test")),
			patch("frappe.get_roles", return_value=["TC R03"]),
		):
			with self.assertRaises(frappe.PermissionError):
				records(role="R01", screen="overrides")

	def test_unknown_screen_is_denied(self):
		from tracecore.v1.admin_ui import records

		with patch("frappe.session", frappe._dict(user="Administrator")):
			with self.assertRaises(frappe.PermissionError):
				records(role="R01", screen="User")

	def test_desk_guard_preserves_station(self):
		from tracecore.ui.admin_access import is_desk_path

		self.assertTrue(is_desk_path("/app/home"))
		self.assertTrue(is_desk_path("/app"))
		self.assertFalse(is_desk_path("/app/station"))
		self.assertFalse(is_desk_path("/app/station/"))
		self.assertTrue(is_desk_path("/app/station-other"))
		self.assertFalse(is_desk_path("/api/method/test"))
