"""Tiêu hao tự động theo lô giặt (FEAT-034, FR-M3-04, BRU-INV-002; A-50 D6, D7)."""

from unittest.mock import patch

import frappe

from tracecore.inventory import consume
from tracecore.inventory.tests.test_consume import ITEM, OTHER_ITEM, ConsumeCase, stock_of
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


class LaundryConsumeCase(ConsumeCase):
	def setUp(self):
		super().setUp()
		factories.make_chemical_batch(OTHER_ITEM, "F34-IND-1", expiry_days=60, qty=100)
		self.washer = factories.make_equipment(
			equipment_type="Laundry Washer", serial="LW-" + frappe.generate_hash(length=8), zone_out=None
		)
		self.program = factories.make_program(
			self.washer.name,
			code="MG-" + frappe.generate_hash(length=6).upper(),
			consumables=[
				{"item": ITEM, "qty_per_load": 1, "qty_per_kg": 0.5},
				{"item": OTHER_ITEM, "qty_per_kg": 0.1},
			],
		)

	def ctx(self, name="LG-F34-1", kg=10, chemicals=None, result="Pass", **kwargs):
		return {
			"batch": name,
			"batch_type": "In-house",
			"equipment": self.washer.name,
			"program": self.program.name,
			"kg": kg,
			"chemicals": chemicals or [],
			"result": result,
			**kwargs,
		}

	def issued(self, name):
		entries = frappe.get_all(
			"Stock Entry",
			filters={"tc_source_doctype": "Laundry Batch", "tc_source_name": name, "docstatus": 1},
			pluck="name",
		)
		totals = {}
		for entry in entries:
			for row in frappe.get_doc("Stock Entry", entry).items:
				totals[row.item_code] = totals.get(row.item_code, 0) + row.qty
		return totals


@bru("BRU-INV-002")
class TestLaundryComplete(LaundryConsumeCase):
	def test_hook_is_registered(self):
		self.assertIn(
			"tracecore.inventory.consume.on_laundry_complete",
			frappe.get_hooks("tracecore_after_laundry_complete"),
		)

	def test_program_norm_is_per_load_plus_per_kg_times_weight(self):  # FR-M3-04
		consume.on_laundry_complete(self.ctx(kg=10))
		self.assertEqual(self.issued("LG-F34-1"), {ITEM: 6, OTHER_ITEM: 1})
		self.assertEqual(stock_of(ITEM), 9)

	def test_chemical_quantity_chosen_by_the_operator_replaces_the_norm_of_that_item(self):
		consume.on_laundry_complete(self.ctx(chemicals=[{"item": ITEM, "qty": 3}]))
		self.assertEqual(self.issued("LG-F34-1"), {ITEM: 3, OTHER_ITEM: 1})

	def test_chemical_with_zero_quantity_falls_back_to_the_norm(self):
		consume.on_laundry_complete(self.ctx(chemicals=[{"item": ITEM, "qty": 0}]))
		self.assertEqual(self.issued("LG-F34-1")[ITEM], 6)

	def test_failed_batch_still_consumes_the_chemicals(self):  # A-50 D7
		consume.on_laundry_complete(self.ctx(result="Fail"))
		self.assertEqual(self.issued("LG-F34-1"), {ITEM: 6, OTHER_ITEM: 1})

	def test_same_batch_is_issued_once(self):
		consume.on_laundry_complete(self.ctx())
		consume.on_laundry_complete(self.ctx())
		self.assertEqual(stock_of(ITEM), 9)

	def test_outsourced_batch_deducts_nothing(self):  # UC-17 A2
		consume.on_laundry_complete(self.ctx(batch_type="Outsourced", equipment=None, program=None))
		self.assertEqual(self.issued("LG-F34-1"), {})

	def test_program_without_norm_reports_instead_of_failing(self):  # FR-M3-04.2
		bare = factories.make_program(self.washer.name, code="MG-BARE", consumables=[])
		with patch.object(consume, "_notify") as notify:
			consume.on_laundry_complete(self.ctx(program=bare.name))
		self.assertEqual(self.issued("LG-F34-1"), {})
		self.assertEqual(notify.call_args.args[0], "CONSUMPTION_NO_NORM")
