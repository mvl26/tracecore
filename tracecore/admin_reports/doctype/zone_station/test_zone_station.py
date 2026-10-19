import frappe
from frappe.tests.utils import FrappeTestCase


class TestZoneStation(FrappeTestCase):
	def test_fixture_zones(self):
		for zone, zone_type in (
			("ZONE-DIRTY", "Dirty"),
			("ZONE-CLEAN", "Clean"),
			("ZONE-STERILE", "Sterile"),
		):
			doc = frappe.get_doc("Zone Station", zone)
			self.assertEqual(doc.is_zone, 1)
			self.assertEqual(doc.zone_type, zone_type)

		station = frappe.get_doc("Zone Station", "TR-004")
		self.assertEqual(station.is_zone, 0)
		self.assertEqual(station.parent_zone, "ZONE-CLEAN")
		self.assertEqual(station.zone_type, "Clean")
		self.assertEqual(station.station_step, "T4")

	def test_station_takes_zone_type_from_parent(self):
		doc = frappe.get_doc(
			{
				"doctype": "Zone Station",
				"zone_station_name": "Test station",
				"is_zone": 0,
				"parent_zone": "ZONE-STERILE",
				"zone_type": "Dirty",
				"station_step": "T6",
			}
		).insert()
		self.assertTrue(doc.name.startswith("TR-"))
		self.assertEqual(doc.zone_type, "Sterile")

	def test_station_requires_zone_parent(self):
		base = {"doctype": "Zone Station", "zone_station_name": "Bad station", "is_zone": 0}
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(dict(base)).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(dict(base, parent_zone="TR-001")).insert()
