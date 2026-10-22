import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

FIXTURES = Path(__file__).parents[2] / "fixtures"


class TestStationAuthModels(FrappeTestCase):
	def test_employee_auth_custom_fields_are_secure(self):
		fields = {
			row["fieldname"]: row
			for row in json.loads((FIXTURES / "custom_field.json").read_text(encoding="utf-8"))
			if row["dt"] == "Employee"
		}
		self.assertEqual(set(fields), {"tc_card_id", "tc_card_enabled", "tc_pin_hash", "tc_pin_reset_required"})
		self.assertEqual(fields["tc_pin_reset_required"]["fieldtype"], "Check")
		self.assertEqual(fields["tc_pin_reset_required"]["read_only"], 1)
		self.assertEqual(fields["tc_pin_reset_required"]["no_copy"], 1)
		self.assertEqual(fields["tc_card_id"]["unique"], 1)
		self.assertEqual(fields["tc_pin_hash"]["fieldtype"], "Password")
		self.assertEqual(fields["tc_pin_hash"]["hidden"], 1)
		self.assertEqual(fields["tc_pin_hash"]["no_copy"], 1)

	def test_temporary_competency_cannot_exceed_24_hours(self):
		start = now_datetime()
		doc = frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": "EMP-TEST",
				"station": "TR-004",
				"valid_from": start,
				"valid_until": add_to_date(start, hours=25),
				"is_temporary": 1,
				"temporary_reason": "Thiếu người ca đêm",
				"approved_by": "Administrator",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_temporary_competency_requires_reason_and_approver(self):
		start = now_datetime()
		doc = frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": "EMP-TEST",
				"station": "TR-004",
				"valid_from": start,
				"valid_until": add_to_date(start, hours=8),
				"is_temporary": 1,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_station_session_never_stores_plain_token(self):
		meta = frappe.get_meta("Station Session")
		token = meta.get_field("token_hash")
		self.assertEqual(token.fieldtype, "Data")
		self.assertTrue(token.hidden)
		self.assertTrue(token.unique)
		self.assertIsNone(meta.get_field("token"))

	def test_station_auth_models_have_no_delete_permission(self):
		for doctype in ("Station Competency", "Station Session"):
			for permission in frappe.get_meta(doctype).permissions:
				self.assertFalse(permission.delete, f"{doctype}/{permission.role} must not delete")
