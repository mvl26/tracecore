"""Contract and authorization for the independent TraceCore Home."""

import hashlib
import json
from copy import deepcopy
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.v1 import home
from tracecore.v1.navigation import context as navigation_context


class TestHomeContext(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")

	def actor(self, roles, user="home@example.test"):
		self.enterContext(patch("frappe.session", frappe._dict(user=user)))
		self.enterContext(patch("frappe.get_roles", return_value=roles))
		# Identity is not the behavior under test; keep role tests independent of User fixtures.
		self.enterContext(patch("frappe.get_cached_value", return_value="Home User"))

	def test_guest_cannot_read_home(self):
		self.actor([], "Guest")
		with self.assertRaises(frappe.PermissionError):
			home.context()

	def test_r03_receives_station_shortcut_without_admin_link(self):
		self.actor(["TC R03"])
		with (
			patch("frappe.has_permission", side_effect=lambda dt, **kw: dt == "Zone Station"),
			patch(
				"frappe.get_list",
				return_value=[
					frappe._dict(name="TR-001", station_step="T1", zone_station_name="Receiving"),
					frappe._dict(name="TR-002", station_step="T2", zone_station_name="Washing"),
					frappe._dict(name="TR-004", station_step="T4", zone_station_name="Packing"),
				],
			) as query,
		):
			expected = navigation_context()["stations"]
			result = home.context()
		self.assertEqual(result["user"]["stations"], expected)
		self.assertIn("station", [item["route_key"] for item in result["shortcuts"]])
		self.assertNotIn("frappe-admin", result["capabilities"])
		self.assertNotIn("frappe-admin", [item["route_key"] for item in result["navigation"]])
		self.assertEqual(query.call_args.kwargs["filters"], {"is_zone": 0, "is_active": 1})

	def test_system_manager_receives_frappe_admin_capability(self):
		for user, roles in (("home@example.test", ["System Manager"]), ("Administrator", [])):
			with (
				self.subTest(user=user),
				patch("frappe.session", frappe._dict(user=user)),
				patch("frappe.get_roles", return_value=roles),
				patch("frappe.get_cached_value", return_value="Home User"),
				patch("frappe.has_permission", return_value=False),
			):
				result = home.context()
				self.assertIn("frappe-admin", result["capabilities"])
				self.assertIn("frappe-admin", [item["route_key"] for item in result["navigation"]])

	def test_doctype_shortcut_requires_read_permission(self):
		self.actor(["TC R01"])
		for doctype, route_key in (
			("Set Unit", "set-units"),
			("Pack", "packs"),
			("Equipment", "equipment"),
			("Par Level", "par-levels"),
		):
			with (
				self.subTest(doctype=doctype),
				patch("frappe.has_permission", side_effect=lambda dt, **kw: dt == doctype),
				patch("frappe.get_list", return_value=[frappe._dict(value=7)]),
			):
				result = home.context()
				for section in ("shortcuts", "navigation"):
					self.assertEqual(
						{item["route_key"] for item in result[section]} - {"search"}, {route_key}
					)
				self.assertEqual({item["route_key"] for item in result["metrics"]}, {route_key})
		with patch("frappe.has_permission", return_value=False), patch("frappe.get_list") as query:
			result = home.context()
			self.assertEqual(result["metrics"], [])
			self.assertEqual(result["user"]["stations"], [])
			query.assert_not_called()

	def test_metrics_use_real_counts_and_never_patient_fields(self):
		result = home.context()
		self.assertTrue(result["metrics"])
		for metric in result["metrics"]:
			doctype = {
				"set-units": "Set Unit",
				"packs": "Pack",
				"equipment": "Equipment",
				"par-levels": "Par Level",
			}[metric["key"]]
			self.assertEqual(metric["value"], frappe.db.count(doctype))
			self.assertIsInstance(metric["value"], int)
		self.assertNotIn("patient", json.dumps(result).lower())
		self.assertEqual(result["attention"], [])

	def test_metrics_respect_record_permissions(self):
		self.actor(["TC R08"])
		with (
			patch("frappe.has_permission", side_effect=lambda dt, **kw: dt == "Set Unit"),
			patch("frappe.get_list", return_value=[frappe._dict(value=3)]) as query,
			patch("frappe.db.count", side_effect=AssertionError("unrestricted count")),
		):
			result = home.context()
		self.assertEqual(result["metrics"][0]["value"], 3)
		self.assertEqual(query.call_args.args, ("Set Unit",))
		self.assertEqual(query.call_args.kwargs["fields"], ["count(name) as value"])
		self.assertFalse(query.call_args.kwargs.get("ignore_permissions"))

	def test_route_keys_are_closed_identifiers_not_urls(self):
		result = home.context()
		self.assertEqual(
			set(result),
			{"user", "capabilities", "navigation", "attention", "metrics", "shortcuts", "system", "etag"},
		)
		self.assertEqual(
			home.ROUTE_KEYS,
			frozenset({"station", "search", "set-units", "packs", "equipment", "par-levels", "frappe-admin"}),
		)
		for shortcut in result["shortcuts"]:
			self.assertEqual(set(shortcut), {"key", "label", "description", "route_key", "badge"})
		for section in ("navigation", "attention", "metrics", "shortcuts"):
			for item in result[section]:
				self.assertIn(item["route_key"], home.ROUTE_KEYS)
				self.assertNotIn("url", item)
		self.assertLessEqual(len(result["shortcuts"]), 8)
		self.assertLessEqual(len(result["metrics"]), 6)
		self.assertEqual(result["system"]["api_version"], 1)
		self.assertIn(home.context, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[home.context], ["GET"])

	def test_context_etag_is_stable_for_equal_payload(self):
		first = home.context()
		second = deepcopy(first)
		second["system"]["server_time"] = "2099-01-01T00:00:00+07:00"
		second["etag"] = "previous-etag"
		self.assertEqual(home._etag(first), home._etag(second))
		canonical = deepcopy(first)
		canonical.pop("etag")
		canonical["system"].pop("server_time")
		expected = hashlib.sha256(
			json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
		).hexdigest()[:16]
		self.assertEqual(first["etag"], expected)
		second["user"]["full_name"] = "Changed"
		self.assertNotEqual(home._etag(first), home._etag(second))
		self.assertIn("server_time", first["system"])
