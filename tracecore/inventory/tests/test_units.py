"""Đổi định mức hóa chất sang ml mà không đổi ĐVT tồn kho (ticket T2 31/10/2026; A-72)."""

import frappe

from tracecore.inventory import consume, units
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

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

CHEMICAL = "HC-UN-ENZ"
OTHER_CHEMICAL = "HC-UN-DIS"
INDICATOR = "VT-UN-CI"


def norm_rows(program):
	return frappe.get_all(
		"Program Consumable",
		filters={"parent": program},
		fields=["item", "uom", "qty_per_load", "qty_per_pack"],
		order_by="idx",
	)


@bru("BRU-INV-002")
class TestConvertChemicalNorms(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.make_item(CHEMICAL, "Chemical", has_batch_no=1)
		factories.make_item(OTHER_CHEMICAL, "Chemical", has_batch_no=1)
		factories.make_item(INDICATOR, "Chemical Indicator")
		self.machine = factories.make_wash_machine()
		self.program = factories.make_wash_program(
			self.machine.name,
			chemical=CHEMICAL,
			consumables=[
				{"item": CHEMICAL, "qty_per_load": 0.03, "qty_per_pack": 0.002},
				{"item": INDICATOR, "qty_per_load": 1},
			],
		).name
		self.uom = factories.ITEM_UOM

	def test_dry_run_reports_and_changes_nothing(self):
		report = units.convert_chemical_norms(self.uom, 5000, dry_run=True)
		self.assertEqual(report["items"], sorted([CHEMICAL, OTHER_CHEMICAL]))
		self.assertEqual(report["norm_rows"], 1)
		self.assertEqual(norm_rows(self.program)[0].uom, None)
		self.assertTrue(frappe.db.get_value("UOM", self.uom, "must_be_whole_number"))

	def test_apply_adds_the_conversion_frees_the_unit_and_rewrites_the_norms(self):
		report = units.convert_chemical_norms(self.uom, 5000, dry_run=False)
		self.assertEqual(report["norm_rows"], 1)
		self.assertFalse(frappe.db.get_value("UOM", self.uom, "must_be_whole_number"))
		self.assertAlmostEqual(
			frappe.db.get_value(
				"UOM Conversion Detail", {"parent": CHEMICAL, "uom": units.SMALL_UOM}, "conversion_factor"
			),
			1 / 5000,
			places=9,
		)
		row = norm_rows(self.program)[0]
		self.assertEqual((row.uom, row.qty_per_load, row.qty_per_pack), (units.SMALL_UOM, 150, 10))
		self.assertEqual(consume.stock_qty_of(CHEMICAL, row.qty_per_load, row.uom), 0.03)

	def test_other_item_groups_are_left_alone(self):
		units.convert_chemical_norms(self.uom, 5000, dry_run=False)
		indicator = next(row for row in norm_rows(self.program) if row.item == INDICATOR)
		self.assertEqual((indicator.uom, indicator.qty_per_load), (None, 1))

	def test_second_run_changes_nothing(self):
		units.convert_chemical_norms(self.uom, 5000, dry_run=False)
		again = units.convert_chemical_norms(self.uom, 5000, dry_run=False)
		self.assertEqual((again["norm_rows"], again["conversions_added"]), (0, 0))
		self.assertEqual(norm_rows(self.program)[0].qty_per_load, 150)

	def test_ratio_must_be_positive(self):
		with self.assertRaises(frappe.ValidationError):
			units.convert_chemical_norms(self.uom, 0)
