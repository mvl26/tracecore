import frappe

from tracecore.core import errors, zones
from tracecore.tests.utils import IsolatedTestCase, bru


class TestZones(IsolatedTestCase):
	def test_default_catalog_matches_a64(self):
		self.assertEqual(zones.allowed_functions("Dirty"), ("RECEIVE", "WASH_LOAD", "WASH_UNLOAD"))
		self.assertEqual(
			zones.allowed_functions("Clean"), ("WASH_UNLOAD", "ASSEMBLE", "PACK", "STERI_LOAD", "STERI_UNLOAD")
		)
		self.assertEqual(zones.allowed_functions("Sterile"), ("STERI_UNLOAD", "PUTAWAY", "ISSUE"))
		self.assertEqual(zones.allowed_functions("Department"), ("USE",))
		self.assertEqual(zones.allowed_functions("Linen"), ("LINEN",))
		self.assertEqual(zones.allowed_functions("Waste"), ("WASTE",))
		self.assertEqual(zones.allowed_functions("Unknown"), ())

	def test_gate_of_each_function_is_fixed_by_catalog(self):
		gates = dict(frappe.get_all("Station Function", fields=["name", "gate_step"], as_list=True))
		self.assertEqual(
			{name: gate for name, gate in gates.items() if gate},
			{"RECEIVE": "T1", "WASH_UNLOAD": "T2", "ASSEMBLE": "T3", "PACK": "T4", "STERI_UNLOAD": "T5"},
		)
		self.assertEqual(set(zones.gate_labels()), {"T1", "T2", "T3", "T4", "T5"})
		self.assertEqual(zones.gate_label("T4"), frappe._("Packing"))

	@bru("BRU-FLOW-001")
	def test_check_functions_reads_rules_from_config(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			zones.check_functions("Dirty", ["PACK"])
		message = str(ctx.exception)
		self.assertIn(frappe._("Packing"), message)
		self.assertIn(frappe._("Receiving"), message)
		self.assertIsNone(zones.check_functions("Clean", ["PACK", "ASSEMBLE"]))
		self.assertIsNone(zones.check_functions("Clean", []))
		zone_type = frappe.get_doc("Zone Type", "Dirty")
		zone_type.append("functions", {"station_function": "PACK"})
		zone_type.save(ignore_permissions=True)
		self.assertIsNone(zones.check_functions("Dirty", ["PACK"]))

	def test_check_functions_with_empty_zone_type_gives_validation_error(self):
		for zone_type in (None, ""):
			with self.subTest(zone_type=zone_type), self.assertRaises(frappe.ValidationError):
				zones.check_functions(zone_type, ["PACK"])

	def test_flow_order_decides_next_zone_type(self):
		self.assertEqual(zones.next_zone_type("Dirty"), "Clean")
		self.assertEqual(zones.next_zone_type("Clean"), "Sterile")
		self.assertIsNone(zones.next_zone_type("Sterile"))
		self.assertIsNone(zones.next_zone_type("Linen"))
		frappe.get_doc({"doctype": "Zone Type", "type_name": "TEST Quarantine", "flow_order": 25}).insert(
			ignore_permissions=True
		)
		self.assertEqual(zones.next_zone_type("Clean"), "TEST Quarantine")

	def test_station_functions_and_lookup(self):
		self.assertEqual(zones.station_functions("TR-002"), ["WASH_LOAD", "WASH_UNLOAD"])
		self.assertTrue(zones.station_has_function("TR-004", "PACK"))
		self.assertTrue(zones.station_has_function("TR-004", "ISSUE", "PACK"))
		self.assertFalse(zones.station_has_function("TR-004", "ISSUE"))
		self.assertFalse(zones.station_has_function("ZONE-CLEAN", "PACK"))
		self.assertFalse(zones.station_has_function(None, "PACK"))
		self.assertIn("TR-004", zones.stations_with_function("PACK"))
		self.assertEqual(zones.stations_with_function("PACK", zone="ZONE-DIRTY"), [])

	def test_missing_functions_lists_required_chain_without_station(self):
		self.assertEqual(zones.missing_functions(), [])
		frappe.db.set_value("Zone Station", "TR-006", "is_active", 0)
		self.assertEqual(zones.missing_functions(), ["PUTAWAY"])

	def test_disabling_function_in_use_is_refused(self):
		doc = frappe.get_doc("Station Function", "PACK")
		doc.is_active = 0
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("TR-004", str(ctx.exception))

	def test_system_function_keeps_gate_and_screen(self):
		for field, value in (("gate_step", "T3"), ("screen_key", "wash"), ("process_order", 1)):
			doc = frappe.get_doc("Station Function", "PACK")
			doc.set(field, value)
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				doc.save(ignore_permissions=True)
		doc = frappe.get_doc("Station Function", "PACK")
		doc.function_name = "Đóng gói bàn A"
		doc.save(ignore_permissions=True)

	def test_custom_function_has_no_gate_or_screen(self):
		doc = frappe.get_doc(
			{
				"doctype": "Station Function",
				"function_code": "TEST_NOTE",
				"function_name": "Note",
				"process_order": 15,
			}
		).insert(ignore_permissions=True)
		self.assertEqual((doc.gate_step or None, doc.screen_key or None, doc.is_system), (None, None, 0))
		doc.gate_step = "T3"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_removing_allowed_function_used_by_active_station_is_refused(self):
		zone_type = frappe.get_doc("Zone Type", "Clean")
		zone_type.functions = [row for row in zone_type.functions if row.station_function != "PACK"]
		with self.assertRaises(frappe.ValidationError) as ctx:
			zone_type.save(ignore_permissions=True)
		self.assertIn("TR-004", str(ctx.exception))

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
