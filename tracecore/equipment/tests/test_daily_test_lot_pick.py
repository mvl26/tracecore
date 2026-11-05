"""A-130 (FEAT-093): gợi ý, chọn tay và quét lô gói thử ở Kiểm tra hằng ngày; lô không đúng bị chặn."""

import frappe
from frappe.utils import getdate

from tracecore.core.errors import BlockedError
from tracecore.core.tests.test_run_consumables import test_program
from tracecore.equipment import daily_test
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
	"Department",
	"User",
	"Employee",
]

STATION = "TR-005"
PACK, OTHER = "DT-BD-PACK", "DT-OTHER"


class LotPickCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.ensure_stock_masters()
		factories.use_stock_company(self)
		factories.make_item(PACK, "Test", has_batch_no=1, apply_rules=True)
		frappe.db.set_value("Item", PACK, "has_expiry_date", 1)  # gói thử theo dõi hạn dùng như hộp thật
		self.near = factories.make_chemical_batch(PACK, "DT-BD-NEAR", expiry_days=10, qty=5).name
		self.far = factories.make_chemical_batch(PACK, "DT-BD-FAR", expiry_days=90, qty=5).name
		self.expired = factories.make_chemical_batch(PACK, "DT-BD-OLD", expiry_days=-1).name
		self.other = factories.make_chemical_batch(OTHER, "DT-OTHER-1", expiry_days=90, qty=5).name
		self.machine = factories.make_sterilizer(daily_tested=False)
		test_program(
			self.machine.name,
			"bowie_dick",
			consumables=[{"item": PACK, "role": "Test Pack", "is_required": 1, "qty_per_load": 1}],
		)

	def ended_run(self):
		daily_test.start_run(self.machine.name, "bowie_dick", STATION, consumables_confirmed=True)
		daily_test.end_run(self.machine.name, "bowie_dick")

	def record(self, lot):
		return daily_test.record(
			self.machine.name, "bowie_dick", "Pass", STATION, lot=lot, photo="/files/t.png"
		)

	def blocked(self, lot):
		with self.assertRaises(BlockedError) as raised:
			self.record(lot)
		return raised.exception.block


class TestRunLots(LotPickCase):
	def test_overview_returns_the_test_pack_lot_of_the_ended_run(self):
		self.ended_run()
		row = next(row for row in daily_test.overview() if row["name"] == self.machine.name)
		self.assertEqual(row["run_lots"], {"bowie_dick": self.near})  # lô hạn gần nhất được chọn lúc Bắt đầu
		lots = row["test_programs"]["bowie_dick"]["consumables"][0]["lots"]
		self.assertEqual([lot["batch"] for lot in lots], [self.near, self.far])


class TestRecordLot(LotPickCase):
	def test_wrong_expired_or_unknown_lots_are_refused(self):
		self.ended_run()
		for lot in (self.other, self.expired, "TEST-LOT-1"):
			self.assertEqual(self.blocked(lot).code, "CONSUMABLE_LOT_INVALID", lot)
		self.assertEqual(
			frappe.db.count("Daily Test", {"equipment": self.machine.name, "run_status": "Recorded"}), 0
		)

	def test_chosen_lot_is_recorded_with_its_batch_expiry(self):
		self.ended_run()
		done = self.record(self.far)
		row = frappe.get_doc("Daily Test", done["daily_test"])
		self.assertEqual((row.lot, row.batch), (self.far, self.far))
		self.assertEqual(
			getdate(row.lot_expiry), getdate(frappe.db.get_value("Batch", self.far, "expiry_date"))
		)

	def test_no_lot_uses_the_lot_of_the_run(self):
		self.ended_run()
		row = frappe.get_doc("Daily Test", self.record("")["daily_test"])
		self.assertEqual(row.batch, self.near)
