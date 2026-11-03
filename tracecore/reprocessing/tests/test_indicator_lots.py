"""Lô chỉ thị ở T5b liên kết Batch của kho (A-112 (d); FR-M6-03.8)."""

import frappe

from tracecore.patches.v0_1 import link_consumable_lots_a112
from tracecore.reprocessing.tests.test_releasing import ReleaseCase, blocked
from tracecore.tests import factories

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestLoadIndicatorLot(ReleaseCase):
	def setUp(self):
		super().setUp()
		self.save_data()

	def row(self, name):
		return frappe.get_doc("Load Indicator Result", name)

	def test_lot_in_stock_links_the_batch_item_and_expiry(self):
		lot = factories.make_ci_batch("Steam", expiry_days=40)
		row = self.row(self.indicator("chemical_class_5", lot=lot)["indicator_result"])
		self.assertEqual((row.batch, row.lot, row.indicator_item), (lot, lot, "CI5-STEAM"))
		self.assertTrue(row.lot_expiry)

	def test_expired_or_non_indicator_lot_is_refused(self):
		expired = factories.make_ci_batch("Steam", expiry_days=-3)
		self.assertEqual(blocked(self, self.indicator, "chemical_class_5", lot=expired).code, "INDICATOR_EXPIRED")
		chemical = factories.make_chemical_batch("IL-ENZ", "IL-ENZ-1", expiry_days=30, qty=0).name
		self.assertEqual(
			blocked(self, self.indicator, "chemical_class_5", lot=chemical).code, "INDICATOR_LOT_INVALID"
		)

	def test_lot_not_in_stock_is_kept_as_a_note(self):
		row = self.row(self.indicator("chemical_class_5", lot="CHU-TREN-HOP")["indicator_result"])
		self.assertEqual((row.lot, row.batch), ("CHU-TREN-HOP", None))

	def test_patch_links_old_rows_whose_lot_is_a_batch(self):
		lot = factories.make_ci_batch("Steam", expiry_days=40)
		old = self.indicator("chemical_class_5", lot=lot)["indicator_result"]
		note = self.indicator("chemical_class_5", lot="CHU-TREN-HOP")["indicator_result"]
		frappe.db.set_value("Load Indicator Result", old, {"batch": None, "indicator_item": None})
		link_consumable_lots_a112.execute()
		self.assertEqual(
			frappe.db.get_value("Load Indicator Result", old, ["batch", "indicator_item"]), (lot, "CI5-STEAM")
		)
		self.assertEqual(frappe.db.get_value("Load Indicator Result", note, ["lot", "batch"]), ("CHU-TREN-HOP", None))
