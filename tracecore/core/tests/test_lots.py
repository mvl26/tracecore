"""Lô vật tư trên từng dòng: gợi ý FEFO, kiểm lô, dòng vật tư lưu lô đã chọn (A-112; FR-M6-03.6, BRU-INV-004)."""

import frappe

from tracecore.core import lots, run_consumables
from tracecore.core.errors import BlockedError
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

ENZYME, OTHER = "LT-ENZ", "LT-OTHER"


class LotCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.ensure_stock_masters()
		factories.use_stock_company(self)
		self.far = factories.make_chemical_batch(ENZYME, "LT-ENZ-FAR", expiry_days=90, qty=5).name
		self.near = factories.make_chemical_batch(ENZYME, "LT-ENZ-NEAR", expiry_days=10, qty=5).name
		self.empty = factories.make_chemical_batch(ENZYME, "LT-ENZ-EMPTY", expiry_days=60, qty=0).name
		self.expired = factories.make_chemical_batch(ENZYME, "LT-ENZ-OLD", expiry_days=-1).name
		self.other = factories.make_chemical_batch(OTHER, "LT-OTHER-1", expiry_days=90, qty=5).name

	def assert_invalid(self, batch, item=ENZYME):
		with self.assertRaises(BlockedError) as raised:
			lots.check(item, batch)
		self.assertEqual(raised.exception.block.code, "CONSUMABLE_LOT_INVALID")
		self.assertEqual(raised.exception.block.http_status, 422)
		return raised.exception.block


class TestFefo(LotCase):
	def test_usable_lots_in_stock_come_first_expiry_first(self):
		self.assertEqual([row["batch"] for row in lots.fefo(ENZYME)], [self.near, self.far])
		first = lots.fefo(ENZYME)[0]
		self.assertEqual(first["qty"], 5)
		self.assertEqual(str(first["expiry_date"]), str(frappe.db.get_value("Batch", self.near, "expiry_date")))

	def test_disabled_lots_and_limit(self):
		frappe.db.set_value("Batch", self.near, "disabled", 1)
		self.assertEqual([row["batch"] for row in lots.fefo(ENZYME)], [self.far])
		self.assertEqual(len(lots.fefo(ENZYME, limit=1)), 1)
		self.assertEqual(lots.fefo("LT-NO-SUCH-ITEM"), [])


class TestCheck(LotCase):
	@bru("BRU-INV-004")
	def test_expired_foreign_unknown_or_disabled_lots_are_refused(self):
		self.assertIn(self.expired, self.assert_invalid(self.expired).reason)
		self.assert_invalid(self.other)
		self.assert_invalid("LT-NO-SUCH-LOT")
		frappe.db.set_value("Batch", self.far, "disabled", 1)
		self.assert_invalid(self.far)

	def test_lot_without_stock_is_accepted_with_a_warning_flag(self):
		checked = lots.check(ENZYME, self.empty)
		self.assertEqual((checked["batch"], checked["no_stock"]), (self.empty, True))
		self.assertFalse(lots.check(ENZYME, self.far)["no_stock"])

	def test_near_expiry_flag(self):
		self.assertTrue(lots.check(ENZYME, self.near)["near_expiry"])
		self.assertFalse(lots.check(ENZYME, self.far)["near_expiry"])


class TestRunConsumableLots(LotCase):
	def setUp(self):
		super().setUp()
		self.employee = factories.make_employee()
		washer = factories.make_wash_machine()
		self.program = factories.make_wash_program(
			washer.name, consumables=[{"item": ENZYME, "role": "Chemical", "is_required": 1, "qty_per_load": 2}]
		).name

	def test_payload_offers_fefo_lots_for_each_consumable(self):
		line = run_consumables.payload(self.program)[0]
		self.assertEqual([row["batch"] for row in line["lots"]], [self.near, self.far])

	@bru("BRU-INV-004")
	def test_chosen_lot_is_kept_with_its_expiry(self):
		row = run_consumables.rows(self.program, 1, [{"item": ENZYME, "batch": self.far}], True, self.employee.name)[0]
		self.assertEqual(row["batch"], self.far)
		self.assertEqual(str(row["expiry_date"]), str(frappe.db.get_value("Batch", self.far, "expiry_date")))
		self.assertEqual(row["actual_qty"], 2)  # chỉ gửi lô: số giữ định mức

	def test_no_lot_given_takes_the_fefo_lot(self):
		row = run_consumables.rows(self.program, 1, [], True, self.employee.name)[0]
		self.assertEqual(row["batch"], self.near)

	def test_expired_lot_blocks_the_run(self):
		with self.assertRaises(BlockedError) as raised:
			run_consumables.rows(self.program, 1, [{"item": ENZYME, "batch": self.expired}], True, self.employee.name)
		self.assertEqual(raised.exception.block.code, "CONSUMABLE_LOT_INVALID")

	def test_issue_lines_pin_the_lot_of_the_row(self):
		rows = run_consumables.rows(self.program, 1, [{"item": ENZYME, "batch": self.far}], True, self.employee.name)
		batch = factories.make_wash_batch(
			factories.make_wash_machine(), self.program, [factories.make_wash_ready_set()], consumables=rows
		)
		self.assertEqual(
			run_consumables.issue_lines("Wash Batch", batch.name, {ENZYME: self.near}),
			[{"item": ENZYME, "qty": 2, "batch": self.far}],
		)
