import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry
from tracecore.tests.utils import bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def make_location(location_name="Kệ A1", **fields):
	return frappe.get_doc({"doctype": "Sterile Location", "location_name": location_name, **fields}).insert()


class TestSterileLocation(FrappeTestCase):
	@bru("BRU-ID-001")
	def test_name_is_ke_code_registered_in_code_registry(self):
		location = make_location()
		self.assertRegex(location.name, r"^KE-\d{4}$")
		row = frappe.db.get_value(
			"Code Registry", location.name, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
		)
		self.assertEqual(
			(row.prefix, row.ref_doctype, row.ref_name, row.status),
			("KE", "Sterile Location", location.name, "Active"),
		)

	def test_names_are_unique_and_skip_registered_codes(self):
		code_registry.next_code("KE")  # số đã nằm trong sổ nhưng chưa có kệ
		first, second = make_location("Kệ 1"), make_location("Kệ 2")
		self.assertNotEqual(first.name, second.name)
		self.assertTrue(re.match(r"^KE-\d{4}$", second.name))

	def test_location_name_required(self):
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({"doctype": "Sterile Location"}).insert()

	def test_zone_station_must_be_in_sterile_zone(self):
		with self.assertRaises(frappe.ValidationError):
			make_location("Kệ sai khu", zone_station="TR-001")
		self.assertEqual(make_location("Kệ đúng khu", zone_station="TR-006").zone_station, "TR-006")

	def test_new_location_is_active_and_can_be_deactivated(self):
		location = make_location()
		self.assertEqual(location.is_active, 1)
		location.is_active = 0
		location.save()
		self.assertEqual(frappe.db.get_value("Sterile Location", location.name, "is_active"), 0)

	def test_audit_log_and_no_delete(self):
		location = make_location()
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": "Sterile Location", "ref_name": location.name, "action": "Create"},
			)
		)
		with self.assertRaises(frappe.ValidationError):
			location.delete()

	def test_permissions(self):
		meta = frappe.get_meta("Sterile Location")
		perms = {p.role: p for p in meta.permissions}
		self.assertTrue(perms["TC R10"].write and perms["TC R10"].create)
		self.assertFalse(perms["TC R10"].delete)
		for role in ("TC R06", "TC R02", "TC R01"):
			self.assertTrue(perms[role].read)
			self.assertFalse(perms[role].write)
