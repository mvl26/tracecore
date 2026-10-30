"""RPC tracecore.v1.zone.allowed_steps (FEAT-002 Task 5): Desk lấy chức năng trạm theo khu từ server."""

import frappe

from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import zone as zone_api

# Zone Station có Link User (chủ sở hữu); site CI mới chưa chạy Setup Wizard.
test_ignore = ["User"]


class TestAllowedSteps(IsolatedTestCase):
	@bru("BRU-FLOW-001")
	def test_allowed_steps_rpc(self):
		self.assertEqual(zone_api.allowed_steps("ZONE-CLEAN"), ["T3", "T4", "T5"])
		self.assertEqual(zone_api.allowed_steps("ZONE-DIRTY"), ["T1", "T2"])
		self.assertEqual(zone_api.allowed_steps("ZONE-STERILE"), ["T5b", "T6", "T7"])

	def test_not_a_zone_gives_empty_list(self):
		self.assertEqual(zone_api.allowed_steps("TR-004"), [])
		self.assertEqual(zone_api.allowed_steps("ZONE-NOPE"), [])
		self.assertEqual(zone_api.allowed_steps(None), [])
		self.assertEqual(zone_api.allowed_steps(["ZONE-CLEAN"]), [])

	def test_zone_without_functions_gives_empty_list(self):
		frappe.db.set_value("Zone Station", "ZONE-CLEAN", "zone_type", "Unknown")
		self.assertEqual(zone_api.allowed_steps("ZONE-CLEAN"), [])


class TestNextZone(IsolatedTestCase):
	@bru("BRU-FLOW-001")
	def test_next_zone_follows_flow(self):
		self.assertEqual(zone_api.next_zone("ZONE-DIRTY"), "ZONE-CLEAN")
		self.assertEqual(zone_api.next_zone("ZONE-CLEAN"), "ZONE-STERILE")

	def test_last_zone_station_and_unknown_give_empty(self):
		self.assertEqual(zone_api.next_zone("ZONE-STERILE"), "")
		self.assertEqual(zone_api.next_zone("TR-004"), "")
		self.assertEqual(zone_api.next_zone("ZONE-NOPE"), "")
		self.assertEqual(zone_api.next_zone(None), "")
		self.assertEqual(zone_api.next_zone(["ZONE-CLEAN"]), "")

	def test_zone_outside_flow_gives_empty(self):
		frappe.db.set_value("Zone Station", "ZONE-CLEAN", "zone_type", "Linen")
		self.assertEqual(zone_api.next_zone("ZONE-CLEAN"), "")
