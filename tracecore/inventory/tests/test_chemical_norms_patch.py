"""Patch đổi định mức hóa chất sang ml và tiêu hao lại các lô đã báo lỗi (ticket T2 31/10/2026; A-72)."""

import frappe

from tracecore.core import client_time
from tracecore.inventory import consume
from tracecore.inventory.tests.test_consume import ITEM, ConsumeCase
from tracecore.patches.v0_1 import chemical_norms_to_ml
from tracecore.reprocessing import washing
from tracecore.tests import factories
from tracecore.tests.utils import bru

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]


def lot_total(item):
	return sum(lot.qty for lot in consume._stock_by_lot(item))


@bru("BRU-INV-002")
class TestChemicalNormsPatch(ConsumeCase):
	def setUp(self):
		super().setUp()
		self.machine = factories.make_wash_machine()
		self.program = factories.make_wash_program(
			self.machine.name,
			chemical=ITEM,
			consumables=[{"item": ITEM, "qty_per_load": 0.03}],
		)
		unit = factories.make_wash_ready_set()
		self.batch = washing.start(
			self.machine.name,
			self.program.name,
			[unit.name],
			[{"item": ITEM, "lot": self.far, "qty": 0}],
			"TR-002",
			client_time.utc_now(),
			factories.make_employee().name,
		)["batch"]
		frappe.db.set_value("Wash Batch", self.batch, "cycle_result", "Pass")
		# lô hoàn thành khi ĐVT còn bắt buộc số nguyên: tiêu hao lỗi và R09 nhận CONSUMPTION_FAILED
		consume.on_wash_complete(consume.wash_context(self.batch))
		frappe.get_doc(
			{
				"doctype": "Notification Delivery",
				"recipient": "Administrator",
				"event_code": "CONSUMPTION_FAILED",
				"channel": "In App",
				"ref_doctype": "Wash Batch",
				"ref_name": self.batch,
				"subject": "x",
			}
		).insert(ignore_permissions=True)

	def test_the_failed_batch_starts_without_an_issue(self):
		self.assertEqual(lot_total(ITEM), 15)

	def test_patch_converts_the_norms_and_issues_the_failed_batch(self):
		chemical_norms_to_ml.run(factories.ITEM_UOM, 5000)
		row = frappe.get_all(
			"Program Consumable", filters={"parent": self.program.name}, fields=["uom", "qty_per_load"]
		)[0]
		self.assertEqual((row.uom, row.qty_per_load), ("ml", 150))
		self.assertAlmostEqual(15 - lot_total(ITEM), 0.03, places=6)

	def test_running_it_again_issues_nothing_more(self):
		chemical_norms_to_ml.run(factories.ITEM_UOM, 5000)
		after_first = lot_total(ITEM)
		chemical_norms_to_ml.run(factories.ITEM_UOM, 5000)
		self.assertEqual(lot_total(ITEM), after_first)

	def test_batch_that_never_failed_is_not_touched(self):
		frappe.db.delete("Notification Delivery", {"ref_name": self.batch})
		chemical_norms_to_ml.run(factories.ITEM_UOM, 5000)
		self.assertEqual(lot_total(ITEM), 15)

	def test_site_without_the_unit_is_left_alone(self):
		chemical_norms_to_ml.execute()  # không có ĐVT "Can" trên site test: không làm gì, không lỗi
		self.assertEqual(lot_total(ITEM), 15)
