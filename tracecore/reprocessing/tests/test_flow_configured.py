"""Cùng kịch bản đi trọn chuỗi của `test_flow_t1_t8` trên sơ đồ 10 trạm yhct (FEAT-051, A-64; AC-1, AC-3, AC-4, AC-6, AC-10)."""

import frappe

from tracecore.core import step_gate, zones
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import assembly, packing, sterilizing, washing
from tracecore.reprocessing.tests.test_flow_t1_t8 import TestFlowT1ToT8
from tracecore.setup.migrate_a64 import apply_yhct
from tracecore.tests.factories import make_sterilizer, make_wash_machine
from tracecore.tests.utils import bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestFlowConfiguredStations(TestFlowT1ToT8):
	RECEIVE = "TR-001"
	WASH_IN = "TR-003"
	WASH_OUT = "TR-004"
	ASSEMBLE = "TR-005"  # bản nháp lắp ráp ở bàn 1, đóng gói ở bàn 2: hai bàn cùng chức năng
	PACK = "TR-006"
	STERI_IN = "TR-007"
	STERI_OUT = "TR-008"
	STORE = "TR-009"
	ISSUE = "TR-010"
	USE = "TR-011"

	def setUp(self):
		super().setUp()
		apply_yhct(dry_run=False)

	@bru("BRU-FLOW-003")
	def test_chart_keeps_every_required_function_and_five_gates(self):
		self.assertEqual(zones.missing_functions(), [])
		self.assertEqual(step_gate.STEPS, ("T1", "T2", "T3", "T4", "T5"))

	def test_manual_wash_station_has_no_business_screen(self):
		self.assertEqual(zones.station_functions("TR-002"), ["MANUAL_WASH"])
		self.assertEqual(zones.station_screen_tabs(["MANUAL_WASH"]), [])

	def test_each_screen_is_refused_at_a_station_without_its_function(self):
		for call in (
			lambda: assembly._require_station("TR-004"),
			lambda: packing._require_station("TR-003"),
		):
			with self.assertRaises(BlockedError) as raised:
				call()
			self.assertEqual(raised.exception.block.code, "STATION_WRONG_STEP")
		assembly._require_station("TR-006")
		packing._require_station("TR-005")

	def test_load_station_cannot_unload_two_door_machines(self):
		washer = make_wash_machine(has_printout=1)
		frappe.db.set_value("Equipment", washer.name, {"zone_in": "ZONE-DIRTY", "zone_out": "ZONE-CLEAN"})
		machine = frappe._dict(zone_in="ZONE-DIRTY", zone_out="ZONE-CLEAN", name=washer.name)
		with self.assertRaises(BlockedError):
			washing._check_unload_station("TR-003", machine)
		washing._check_unload_station("TR-004", machine)

		sterilizer = make_sterilizer()
		door = frappe._dict(zone_in="ZONE-CLEAN", zone_out="ZONE-STERILE", name=sterilizer.name)
		with self.assertRaises(BlockedError):
			sterilizing._check_data_station("TR-007", door, unload_only=True)
		sterilizing._check_data_station("TR-007", door)  # nhập dữ liệu chu trình ở trạm nạp vẫn được
		sterilizing._check_data_station("TR-008", door, unload_only=True)

	def test_next_station_prefers_itself_when_it_also_packs(self):
		self.assertEqual(assembly._next_station("TR-005"), "TR-005")
