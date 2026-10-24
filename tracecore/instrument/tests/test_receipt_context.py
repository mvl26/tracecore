"""Hook ``tracecore_receipt_context`` (FEAT-019, A-32): BOM và ảnh áp dụng tại ngày tiếp nhận cho màn T1."""

from datetime import datetime

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import extension
from tracecore.instrument import bom
from tracecore.tests.factories import make_bom, make_set_type, make_set_unit
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestReceiptContext(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.set_type = make_set_type("RCTX", bom=[("RC-KC-01", 2), ("RC-KC-02", 1)]).name
		make_bom(self.set_type, [("RC-KC-01", 3)], version=2, effective_from=add_days(today(), 1))
		self.unit = make_set_unit(self.set_type).name

	def context(self, on):
		return bom.receipt_context({"set_unit": self.unit, "set_type": self.set_type, "on": on})

	def test_hook_is_registered_for_the_receiving_service(self):
		self.assertIn("tracecore.instrument.bom.receipt_context", frappe.get_hooks("tracecore_receipt_context"))
		results = extension.run(
			"tracecore_receipt_context",
			{"set_unit": self.unit, "set_type": self.set_type, "on": datetime.now()},
		)
		self.assertEqual(results[0]["bom_version"], 1)

	@bru("BRU-REP-012")
	def test_lines_follow_bom_order_with_names_and_photos(self):
		data = self.context(datetime.now())
		self.assertEqual(data["bom_version"], 1)
		self.assertEqual([line["instrument"] for line in data["bom"]], ["RC-KC-01", "RC-KC-02"])
		self.assertEqual([line["qty"] for line in data["bom"]], [2, 1])
		for line in data["bom"]:
			self.assertTrue(line["instrument_name"])
			self.assertIn("thumbnail", line)  # None khi chưa có ảnh: màn T1 hiện khung "Chưa có ảnh"
			self.assertIn("image", line)
		self.assertEqual(data["tray_images"], [])

	def test_version_follows_the_system_day_of_the_scan(self):
		tomorrow = datetime.combine(getdate(add_days(today(), 1)), datetime.min.time())
		self.assertEqual(self.context(tomorrow)["bom_version"], 2)
		self.assertEqual(self.context(tomorrow)["bom"][0]["qty"], 3)
		self.assertEqual(self.context(datetime.now())["bom_version"], 1)

	def test_set_type_without_bom_gives_empty_context(self):
		bare = make_set_type("RCNB").name
		data = bom.receipt_context({"set_unit": None, "set_type": bare, "on": datetime.now()})
		self.assertEqual((data["bom_version"], data["bom"]), (0, []))
