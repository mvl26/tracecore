"""Tiêu hao hóa chất theo ĐVT nhỏ (ml) khi tồn kho tính theo Can (ticket T2 31/10/2026; A-72, FEAT-042, BRU-INV-002)."""

from unittest.mock import patch

import frappe

from tracecore.core import client_time
from tracecore.inventory import consume
from tracecore.inventory.tests.test_consume import ITEM, ConsumeCase
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

ML_PER_STOCK_UNIT = 5000  # 1 Can = 5.000 ml


def stock_of(item):
	"""Tồn theo lô (Bin làm tròn 2 số lẻ nên không dùng để so số lẻ nhỏ)."""
	return sum(lot.qty for lot in consume._stock_by_lot(item))


def allow_fractions(allowed=True):
	frappe.db.set_value("UOM", factories.ITEM_UOM, "must_be_whole_number", 0 if allowed else 1)
	frappe.clear_cache(doctype="UOM")


def add_ml(item=ITEM):
	if not frappe.db.exists("UOM", "ml"):
		frappe.get_doc({"doctype": "UOM", "uom_name": "ml", "must_be_whole_number": 0}).insert(
			ignore_permissions=True
		)
	doc = frappe.get_doc("Item", item)
	doc.flags.tc_legacy_data = True
	doc.append("uoms", {"uom": "ml", "conversion_factor": 1 / ML_PER_STOCK_UNIT})
	doc.save(ignore_permissions=True)


class UomCase(ConsumeCase):
	def setUp(self):
		super().setUp()
		add_ml()
		self.machine = factories.make_wash_machine()
		self.program = factories.make_wash_program(
			self.machine.name,
			chemical=ITEM,
			consumables=[{"item": ITEM, "qty_per_load": 100, "qty_per_pack": 25, "uom": "ml"}],
		)

	def ctx(self, name="WB-UOM-1", sets=("S1", "S2")):
		return {
			"batch": name,
			"equipment": self.machine.name,
			"program": self.program.name,
			"sets": list(sets),
			"chemicals": [{"item": ITEM, "lot": self.far, "qty": 0}],
			"result": "Pass",
		}


@bru("BRU-INV-002")
class TestNormInMillilitres(UomCase):
	def test_norm_in_ml_is_issued_as_a_fraction_of_the_stock_unit(self):
		allow_fractions()
		before = stock_of(ITEM)
		consume.on_wash_complete(self.ctx())
		# 100 + 25 x 2 bộ = 150 ml = 0,03 Can
		self.assertAlmostEqual(before - stock_of(ITEM), 150 / ML_PER_STOCK_UNIT, places=6)

	def test_norm_without_uom_still_means_the_stock_unit(self):
		allow_fractions()
		program = factories.make_wash_program(
			self.machine.name, chemical=ITEM, consumables=[{"item": ITEM, "qty_per_load": 1}]
		)
		before = stock_of(ITEM)
		consume.on_wash_complete({**self.ctx("WB-UOM-2"), "program": program.name})
		self.assertEqual(before - stock_of(ITEM), 1)

	def test_missing_conversion_names_the_unit_and_the_item(self):
		if not frappe.db.exists("UOM", "Kg"):
			frappe.get_doc({"doctype": "UOM", "uom_name": "Kg"}).insert(ignore_permissions=True)
		with self.assertRaises(consume.UomConversionMissing) as raised:
			consume._norm_stock_qty(
				frappe._dict(item=ITEM, uom="Kg", qty_per_load=1, qty_per_pack=0, qty_per_kg=0), 1
			)
		self.assertIn("Kg", str(raised.exception))
		self.assertIn(ITEM, str(raised.exception))


@bru("BRU-INV-002")
class TestFailureTellsTheCause(UomCase):
	def test_whole_number_unit_failure_is_explained_in_the_notification(self):
		allow_fractions(False)
		with patch("tracecore.inventory.consume.notification.emit") as emit:
			consume.on_wash_complete(self.ctx())
		self.assertEqual(emit.call_args.args[0], "CONSUMPTION_FAILED")
		message = emit.call_args.kwargs["message"]
		self.assertIn(ITEM, message)
		self.assertIn("0.03", message)

	def test_failure_points_to_the_batch_and_the_retry_action(self):
		allow_fractions(False)
		with patch("tracecore.inventory.consume.notification.emit") as emit:
			consume.on_wash_complete(self.ctx())
		self.assertIn("tc_source_name=WB-UOM-1", emit.call_args.kwargs["link"])  # #1833: nút mở phiếu xuất
		self.assertIn("retry", emit.call_args.kwargs["message"].lower())


@bru("BRU-INV-002")
class TestRetry(UomCase):
	def make_passed_batch(self):
		unit = factories.make_wash_ready_set()
		batch = washing.start(
			self.machine.name,
			self.program.name,
			[unit.name],
			[{"item": ITEM, "lot": self.far, "qty": 0}],
			"TR-002",
			client_time.utc_now(),
			factories.make_employee().name,
		)["batch"]
		frappe.db.set_value("Wash Batch", batch, "cycle_result", "Pass")
		return batch

	def test_retry_issues_what_the_failed_run_could_not(self):
		allow_fractions(False)
		batch = self.make_passed_batch()
		with patch("tracecore.inventory.consume.notification.emit"):
			consume.on_wash_complete(consume.wash_context(batch))
		self.assertEqual(stock_of(ITEM), 15)
		allow_fractions(True)
		result = consume.retry("Wash Batch", batch)
		self.assertTrue(result["created"])
		self.assertAlmostEqual(15 - stock_of(ITEM), 125 / ML_PER_STOCK_UNIT, places=6)  # 100 + 25 x 1 bộ

	def test_retry_twice_does_not_double_issue(self):
		allow_fractions(True)
		batch = self.make_passed_batch()
		consume.retry("Wash Batch", batch)
		after_first = stock_of(ITEM)
		again = consume.retry("Wash Batch", batch)
		self.assertFalse(again["created"])
		self.assertEqual(stock_of(ITEM), after_first)

	def test_retry_refuses_a_batch_that_did_not_pass(self):
		batch = self.make_passed_batch()
		frappe.db.set_value("Wash Batch", batch, "cycle_result", "Fail")
		with self.assertRaises(frappe.ValidationError):
			consume.retry("Wash Batch", batch)

	def test_retry_failure_raises_with_the_cause(self):
		allow_fractions(False)
		batch = self.make_passed_batch()
		with self.assertRaises(frappe.ValidationError) as raised:
			consume.retry("Wash Batch", batch)
		self.assertIn("0.025", str(raised.exception))
