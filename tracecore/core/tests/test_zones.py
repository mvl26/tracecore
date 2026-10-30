import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import errors, zones
from tracecore.tests.utils import bru


class TestZones(FrappeTestCase):
	def test_allowed_steps_by_zone_type(self):
		self.assertEqual(zones.allowed_steps("Dirty"), ("T1", "T2"))
		self.assertEqual(zones.allowed_steps("Clean"), ("T3", "T4", "T5"))
		self.assertEqual(zones.allowed_steps("Sterile"), ("T5b", "T6", "T7"))
		self.assertEqual(zones.allowed_steps("Department"), ("T8",))
		self.assertEqual(zones.allowed_steps("Linen"), ("LIN",))
		self.assertEqual(zones.allowed_steps("Waste"), ())
		self.assertEqual(zones.allowed_steps("Unknown"), ())
		self.assertEqual(zones.ZONE_FLOW, ("Dirty", "Clean", "Sterile"))

	@bru("BRU-FLOW-001")
	def test_check_step_rejects_step_outside_zone(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			zones.check_step("Dirty", "T4")
		self.assertIn("T1", str(ctx.exception))
		self.assertIn("T2", str(ctx.exception))
		self.assertIsNone(zones.check_step("Clean", "T4"))
		with self.assertRaises(frappe.ValidationError) as ctx:
			zones.check_step("Linen", "T1")
		self.assertNotIn("T1,", str(ctx.exception))
		self.assertIsNone(zones.check_step("Clean", None))
		self.assertIsNone(zones.check_step("Clean", ""))

	def test_check_step_with_empty_zone_type_gives_validation_error(self):
		"""Khu chưa có loại (None/rỗng): báo lỗi nghiệp vụ, không lỗi lập trình."""
		for zone_type in (None, ""):
			with self.subTest(zone_type=zone_type), self.assertRaises(frappe.ValidationError):
				zones.check_step(zone_type, "T4")
		self.assertEqual(zones._zone_type_label(None), "")

	@bru("BRU-FLOW-001")
	def test_pass_through_must_go_to_next_zone(self):
		self.assertIsNone(zones.check_pass_through("ZONE-DIRTY", "ZONE-CLEAN"))
		self.assertIsNone(zones.check_pass_through("ZONE-CLEAN", "ZONE-STERILE"))
		self.assertIsNone(zones.check_pass_through("ZONE-DIRTY", None))
		self.assertIsNone(zones.check_pass_through("ZONE-CLEAN", ""))
		for zone_in, zone_out in (
			("ZONE-DIRTY", "ZONE-STERILE"),
			("ZONE-CLEAN", "ZONE-DIRTY"),
			("ZONE-STERILE", "ZONE-DIRTY"),
			("ZONE-STERILE", "ZONE-CLEAN"),
			("ZONE-DIRTY", "ZONE-DIRTY"),
			("TR-004", "ZONE-STERILE"),  # trạm, không phải khu
			("ZONE-CLEAN", "TR-006"),
			("", "ZONE-CLEAN"),
			(None, None),
			("NO-SUCH-ZONE", None),
			("ZONE-DIRTY", "NO-SUCH-ZONE"),
		):
			with self.subTest(zone_in=zone_in, zone_out=zone_out), self.assertRaises(frappe.ValidationError):
				zones.check_pass_through(zone_in, zone_out)

	def test_pass_through_outside_flow_is_single_door_only(self):
		zone = frappe.get_doc(
			{
				"doctype": "Zone Station",
				"zone_station_name": "TEST Kho Vải",
				"is_zone": 1,
				"zone_type": "Linen",
			}
		).insert(ignore_permissions=True)
		self.assertIsNone(zones.check_pass_through(zone.name, None))
		with self.assertRaises(frappe.ValidationError):
			zones.check_pass_through(zone.name, "ZONE-CLEAN")
		with self.assertRaises(frappe.ValidationError):
			zones.check_pass_through("ZONE-DIRTY", zone.name)

	def test_station_inactive_maps_to_409(self):
		self.assertEqual(errors.Block("STATION_INACTIVE", "t", "r", "a").http_status, 409)
		self.assertEqual(errors.HTTP_STATUS["STATION_INACTIVE"], 409)
