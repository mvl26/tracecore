from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.v1.navigation import context as get_context


class TestLauncher(FrappeTestCase):
	def test_guest_cannot_read_launcher(self):
		with patch("frappe.session", frappe._dict(user="Guest")):
			with self.assertRaises(frappe.PermissionError):
				get_context()

	def test_operator_sees_only_its_steps(self):
		with (
			patch("frappe.session", frappe._dict(user="operator@example.test")),
			patch("frappe.get_roles", return_value=["TC R03"]),
			patch(
				"frappe.get_list",
				return_value=[
					frappe._dict(name="TR-123", station_step="T2", zone_station_name="Washer"),
					frappe._dict(name="TR-456", station_step="T4", zone_station_name="Packing"),
				],
			),
		):
			context = get_context()
		self.assertEqual(context["management"], [])
		self.assertFalse(context["department"])
		self.assertEqual([s["name"] for s in context["stations"]], ["TR-123"])
		self.assertTrue(context["stations"][0]["implemented"])

	def test_pending_station_and_active_filter(self):
		with (
			patch("frappe.session", frappe._dict(user="operator@example.test")),
			patch("frappe.get_roles", return_value=["TC R05"]),
			patch(
				"frappe.get_list",
				return_value=[
					# T1-T8 đều có màn kiosk; trạm gán riêng T5b chưa có (dỡ mẻ là chế độ của màn T5)
					frappe._dict(name="TR-998", station_step="T5", zone_station_name="Load"),
					frappe._dict(name="TR-999", station_step="T5b", zone_station_name="Unload"),
				],
			) as query,
		):
			context = get_context()
		self.assertEqual([s["implemented"] for s in context["stations"]], [True, False])
		self.assertEqual(query.call_args.kwargs["filters"], {"is_zone": 0, "is_active": 1})

	def test_unrelated_account_has_no_operational_choices(self):
		with (
			patch("frappe.session", frappe._dict(user="employee@example.test")),
			patch("frappe.get_roles", return_value=["Employee"]),
			patch("frappe.get_list") as query,
		):
			context = get_context()
		self.assertEqual(context["stations"], [])
		self.assertEqual(context["management"], [])
		query.assert_not_called()

	def test_manager_links_require_doctype_permission(self):
		with (
			patch("frappe.session", frappe._dict(user="manager@example.test")),
			patch("frappe.get_roles", return_value=["TC R01"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", side_effect=lambda dt, **kw: dt == "Pack"),
		):
			context = get_context()
		self.assertEqual([link["doctype"] for link in context["management"]], ["Pack"])
