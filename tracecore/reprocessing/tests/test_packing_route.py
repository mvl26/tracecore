"""A-156 (FEAT-098): bộ quy trình Khử khuẩn không đóng gói tiệt khuẩn ở T4 (FR-M1-03.10)."""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import packing
from tracecore.tests.factories import make_t4_ready_set
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-004"


class TestDisinfectionSetAtT4(IsolatedTestCase):
	def test_disinfection_set_is_blocked_with_reason(self):
		ready = make_t4_ready_set()
		set_type = frappe.db.get_value("Set Unit", ready.set_id, "set_type")
		frappe.db.set_value("Instrument Set Type", set_type, "method", "Disinfection")
		with self.assertRaises(BlockedError) as raised:
			packing.get_context(ready.set_id, STATION)
		block = raised.exception.block
		self.assertEqual((block.code, block.http_status), ("SET_NOT_FOR_STERILIZATION", 409))
		self.assertTrue(block.title and block.reason and block.action)
		self.assertEqual(frappe.get_all("Pack", filters={"set_unit": ready.set_id}), [])
