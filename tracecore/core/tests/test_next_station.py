"""Trạm kế tiếp sau khi xong một bước (A-117, FR-M9-22): mã vạch sang trạm kế ở màn trạm."""

import frappe

from tracecore.core import next_station
from tracecore.setup.migrate_a64 import apply_yhct
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestNextStation(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		apply_yhct(dry_run=False)  # sơ đồ 10 trạm: TR-001 nhận … TR-011 sử dụng

	def station(self, station, function):
		found = next_station.of(station, function)
		return found and found["station"]

	@bru("BRU-FLOW-003")
	def test_each_step_points_to_the_next_function_of_the_chain(self):
		chain = [
			("TR-001", "RECEIVE", "TR-003"),
			("TR-004", "WASH_UNLOAD", "TR-005"),
			("TR-006", "PACK", "TR-007"),
			("TR-007", "STERI_LOAD", "TR-008"),
			("TR-008", "STERI_UNLOAD", "TR-009"),
			("TR-009", "PUTAWAY", "TR-010"),
			("TR-010", "ISSUE", "TR-011"),
		]
		for station, function, expected in chain:
			self.assertEqual(self.station(station, function), expected, function)

	def test_prefers_itself_when_it_also_does_the_next_step(self):
		self.assertEqual(self.station("TR-005", "ASSEMBLE"), "TR-005")  # bàn 1 cũng đóng gói

	def test_last_step_has_no_next_station(self):
		self.assertIsNone(next_station.of("TR-011", "USE"))  # T8: trạm cuối

	def test_unknown_function_has_no_next_station(self):
		self.assertIsNone(next_station.of("TR-001", "NOT_A_FUNCTION"))
		self.assertIsNone(next_station.of(None, "RECEIVE"))

	def test_result_carries_label_and_function(self):
		found = next_station.of("TR-001", "RECEIVE")
		self.assertEqual(found["function"], "WASH_LOAD")
		self.assertTrue(found["label"])

	def test_inactive_station_is_skipped_and_none_when_all_are_off(self):
		frappe.db.set_value("Zone Station", "TR-003", "is_active", 0)
		self.assertNotEqual(self.station("TR-001", "RECEIVE"), "TR-003")  # TR-003 tắt: không được chọn
		for name in frappe.get_all(
			"Zone Station Function", filters={"station_function": "WASH_LOAD"}, pluck="parent"
		):
			frappe.db.set_value("Zone Station", name, "is_active", 0)
		self.assertIsNone(next_station.of("TR-001", "RECEIVE"))
