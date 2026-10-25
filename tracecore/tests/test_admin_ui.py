"""Role-space access is separate from document permissions (Admin UI A-35)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAdminUI(FrappeTestCase):
	def test_schema_omits_fields_at_unreadable_permlevels(self):
		from tracecore.v1.admin_ui import _schema

		meta = frappe._dict(permissions=[frappe._dict(role="TC R02", read=1, permlevel=0)])
		meta.get_field = lambda name: frappe._dict(permlevel=1 if name == "reason" else 0)
		meta.has_field = lambda name: True
		with patch("frappe.get_roles", return_value=["TC R02"]), patch("frappe.get_meta", return_value=meta):
			self.assertEqual(_schema("Audit Log", ["action", "reason"]), ["action"])

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

	def test_list_uses_permission_query_and_bounded_page(self):
		from tracecore.v1.admin_ui import records

		with (
			patch("frappe.session", frappe._dict(user="Administrator")),
			patch("tracecore.v1.admin_ui._availability", return_value="ready"),
			patch("tracecore.v1.admin_ui._schema", return_value=["instrument_name", "status"]),
			patch("frappe.get_list", return_value=[frappe._dict(name=f"I-{i}") for i in range(26)]) as query,
		):
			result = records("R02", "instruments", start=-100)
		self.assertEqual(len(result["rows"]), 25)
		self.assertTrue(result["has_more"])
		self.assertEqual(query.call_args.kwargs["start"], 0)
		self.assertNotIn("ignore_permissions", query.call_args.kwargs)
		self.assertNotIn("password", query.call_args.kwargs["fields"])

	def test_detail_denies_record_outside_query_scope(self):
		from tracecore.v1.admin_ui import detail

		with (
			patch("frappe.session", frappe._dict(user="Administrator")),
			patch("tracecore.v1.admin_ui._availability", return_value="ready"),
			patch("tracecore.v1.admin_ui._schema", return_value=[]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.get_doc") as get_doc,
		):
			with self.assertRaises(frappe.PermissionError):
				detail("R08", "usage", "OTHER-DEPARTMENT")
		get_doc.assert_not_called()

	def test_role_overview_does_not_grant_document_access(self):
		from tracecore.v1.admin_ui import records

		with (
			patch("frappe.session", frappe._dict(user="overview@example.test")),
			patch("frappe.get_roles", return_value=["TC Admin Overview"]),
			patch("tracecore.v1.admin_ui._availability", return_value="forbidden"),
		):
			with self.assertRaises(frappe.PermissionError):
				records("R01", "overrides")

	def test_generic_save_cannot_change_set_lifecycle(self):
		from tracecore.v1.admin_ui import save_master

		with patch("frappe.session", frappe._dict(user="Administrator")):
			with self.assertRaises(frappe.PermissionError):
				save_master("R02", "set-units", {"status": "Sterile"})

	def test_instrument_cannot_accept_protected_fields(self):
		from tracecore.v1.admin_ui import save_master

		with (
			patch("frappe.session", frappe._dict(user="Administrator")),
			patch("tracecore.v1.admin_ui._availability", return_value="ready"),
			patch("tracecore.v1.admin_ui._schema", return_value=[]),
		):
			with self.assertRaises(frappe.ValidationError):
				save_master("R02", "instruments", {"giai_code": "FORGED"})

	def test_real_instrument_create_and_optimistic_edit(self):
		from tracecore.v1.admin_ui import master_form, save_master

		frappe.set_user("Administrator")
		name = "ADMIN-UI-" + frappe.generate_hash(length=8).upper()
		result = save_master(
			"R02",
			"instruments",
			{
				"instrument_code": name,
				"instrument_name": "Admin UI test",
				"spaulding_class": "Critical",
				"compatible_methods": ["Steam 134"],
			},
		)
		self.assertEqual(result["name"], name)
		form = master_form("R02", "instruments", name)
		self.assertEqual(form["values"]["compatible_methods"], ["Steam 134"])
		with self.assertRaises(frappe.TimestampMismatchError):
			save_master("R02", "instruments", {"instrument_name": "Stale"}, name=name, modified="2000-01-01")
		updated = save_master(
			"R02", "instruments", {"instrument_name": "Edited"}, name=name, modified=form["modified"]
		)
		self.assertEqual(updated["name"], name)
		self.assertEqual(frappe.db.get_value("Instrument", name, "instrument_name"), "Edited")


class TestAdminUIRoles(FrappeTestCase):
	def test_admin_overview_and_desk_access_roles_ship_as_fixtures(self):
		# A-35: hai role mới phải có trên mọi site để quản trị cấp được; fixtures của app mang chúng theo
		import json

		from tracecore import hooks

		path = frappe.get_app_path("tracecore", "fixtures", "role.json")
		with open(path, encoding="utf-8") as handle:
			shipped = {row["name"]: row for row in json.load(handle)}
		for role in ("TC Admin Overview", "TraceCore Desk Access"):
			self.assertIn(role, shipped)
			self.assertTrue(frappe.db.exists("Role", role), role)
		role_fixture = next(item for item in hooks.fixtures if item["dt"] == "Role")
		exported = frappe.get_all(
			"Role",
			filters=role_fixture.get("filters"),
			or_filters=role_fixture.get("or_filters"),
			pluck="name",
		)
		self.assertIn("TraceCore Desk Access", exported)
		self.assertIn("TC Admin Overview", exported)


class TestAdminUIRegistry(FrappeTestCase):
	def test_every_screen_field_exists_in_its_doctype(self):
		# trường sai tên bị _schema lọc bỏ âm thầm (cột biến mất); DocType chưa có thì màn báo chưa sẵn sàng
		from tracecore.ui.admin_registry import SCREENS
		from tracecore.v1.admin_ui import STANDARD_FIELDS

		wrong = {}
		for screen, (_title, doctype, fields) in SCREENS.items():
			if not doctype or not frappe.db.exists("DocType", doctype):
				continue
			meta = frappe.get_meta(doctype)
			bad = [field for field in fields if not meta.has_field(field) and field not in STANDARD_FIELDS]
			if bad:
				wrong[screen] = bad
		self.assertEqual(wrong, {})

	def test_docstatus_column_is_kept_for_submittable_screens(self):
		from tracecore.v1.admin_ui import _schema

		with patch("frappe.get_roles", return_value=["Administrator", "TC R02"]):
			self.assertIn("docstatus", _schema("Assembly Record", ["set_unit", "docstatus"]))
