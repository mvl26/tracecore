"""Tiêu hao tự động theo lô rửa / mẻ tiệt khuẩn (FEAT-042, FR-M6-03, BRU-INV-001, BRU-INV-002)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from tracecore.inventory import consume
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

ITEM = "HC-F42-ENZ"
OTHER_ITEM = "HC-F42-IND"


def stock_of(item, warehouse=None):
	filters = {"item_code": item}
	if warehouse:
		filters["warehouse"] = warehouse
	return sum(frappe.get_all("Bin", filters=filters, pluck="actual_qty"))


def lot_qty(batch):
	return sum(lot.qty for lot in consume._stock_by_lot(ITEM) if lot.batch == batch)


class ConsumeCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.masters = factories.ensure_stock_masters()
		factories.use_stock_company(self)
		self.warehouse = self.masters["warehouse"]
		self.near = factories.make_chemical_batch(ITEM, "F42-NEAR", expiry_days=10, qty=5).name
		self.far = factories.make_chemical_batch(ITEM, "F42-FAR", expiry_days=90, qty=10).name

	def entry_rows(self, name):
		return frappe.get_doc("Stock Entry", name).items


@bru("BRU-INV-001")
class TestPickLots(ConsumeCase):
	def test_nearest_expiry_first_and_splits_across_lots(self):
		lots, short = consume.pick_lots(ITEM, 8)
		self.assertEqual([(lot.batch, lot.qty) for lot in lots], [(self.near, 5), (self.far, 3)])
		self.assertEqual(short, 0)

	def test_reports_the_part_that_stock_cannot_cover(self):
		lots, short = consume.pick_lots(ITEM, 20)
		self.assertEqual(sum(lot.qty for lot in lots), 15)
		self.assertEqual(short, 5)

	def test_expired_lot_with_stock_is_never_picked(self):
		frappe.db.set_value("Batch", self.near, "expiry_date", add_days(today(), -1))
		lots, short = consume.pick_lots(ITEM, 8)
		self.assertEqual([(lot.batch, lot.qty) for lot in lots], [(self.far, 8)])
		self.assertEqual(short, 0)

	def test_lot_without_expiry_goes_last(self):
		frappe.db.set_value("Batch", self.near, "expiry_date", None)
		lots, _short = consume.pick_lots(ITEM, 12)
		self.assertEqual([lot.batch for lot in lots], [self.far, self.near])


@bru("BRU-INV-002")
class TestConsumeFor(ConsumeCase):
	def test_creates_one_submitted_material_issue_with_lots_and_source(self):
		result = consume.consume_for("Wash Batch", "WB-F42-1", [{"item": ITEM, "qty": 8}], reason="Auto")
		self.assertTrue(result["created"])
		doc = frappe.get_doc("Stock Entry", result["entry"])
		self.assertEqual((doc.docstatus, doc.purpose), (1, "Material Issue"))
		self.assertEqual((doc.tc_source_doctype, doc.tc_source_name), ("Wash Batch", "WB-F42-1"))
		self.assertEqual({(row.batch_no, row.qty) for row in doc.items}, {(self.near, 5), (self.far, 3)})
		self.assertEqual(stock_of(ITEM), 7)

	def test_company_comes_from_the_warehouse_when_user_has_no_default(self):
		# chạy bằng Administrator hoặc user không có Company mặc định, site nhiều bệnh viện không đặt mặc định chung
		with patch("erpnext.get_default_company", return_value=None):
			result = consume.consume_for("Wash Batch", "WB-F42-CO", [{"item": ITEM, "qty": 1}], reason="Auto")
		company = frappe.db.get_value("Warehouse", self.warehouse, "company")
		self.assertEqual(frappe.db.get_value("Stock Entry", result["entry"], "company"), company)

	def test_same_source_is_issued_once(self):
		first = consume.consume_for("Wash Batch", "WB-F42-2", [{"item": ITEM, "qty": 2}], reason="Auto")
		second = consume.consume_for("Wash Batch", "WB-F42-2", [{"item": ITEM, "qty": 2}], reason="Auto")
		self.assertEqual(second["entry"], first["entry"])
		self.assertFalse(second["created"])
		self.assertEqual(stock_of(ITEM), 13)

	def test_cancelled_entry_does_not_block_a_new_one(self):
		first = consume.consume_for("Wash Batch", "WB-F42-3", [{"item": ITEM, "qty": 2}], reason="Auto")
		frappe.get_doc("Stock Entry", first["entry"]).cancel()
		second = consume.consume_for("Wash Batch", "WB-F42-3", [{"item": ITEM, "qty": 2}], reason="Auto")
		self.assertNotEqual(second["entry"], first["entry"])

	def test_shortage_issues_what_exists_and_records_the_rest(self):
		result = consume.consume_for("Wash Batch", "WB-F42-4", [{"item": ITEM, "qty": 20}], reason="Auto")
		self.assertEqual(result["short"], [{"item": ITEM, "qty": 5}])
		self.assertEqual(stock_of(ITEM), 0)
		doc = frappe.get_doc("Stock Entry", result["entry"])
		self.assertEqual(doc.docstatus, 1)
		self.assertIn(f"{ITEM}: 5", doc.tc_reason)

	def test_no_stock_at_all_creates_no_entry_but_reports_the_shortage(self):
		result = consume.consume_for(
			"Wash Batch", "WB-F42-6", [{"item": "HC-F42-NONE", "qty": 2}], reason="Auto"
		)
		self.assertIsNone(result["entry"])
		self.assertEqual(result["short"], [{"item": "HC-F42-NONE", "qty": 2}])

	def test_zero_quantity_lines_create_nothing(self):
		result = consume.consume_for("Wash Batch", "WB-F42-5", [{"item": ITEM, "qty": 0}], reason="Auto")
		self.assertIsNone(result["entry"])
		self.assertEqual(stock_of(ITEM), 15)


class ProgramCase(ConsumeCase):
	def setUp(self):
		super().setUp()
		factories.make_chemical_batch(OTHER_ITEM, "F42-IND-1", expiry_days=60, qty=100)
		self.machine = factories.make_wash_machine()
		self.program = factories.make_wash_program(
			self.machine.name,
			chemical=ITEM,
			consumables=[
				{"item": ITEM, "qty_per_load": 1, "qty_per_pack": 1},
				{"item": OTHER_ITEM, "qty_per_load": 2, "qty_per_pack": 1},
			],
		)

	def issued(self, doctype, name):
		names = frappe.get_all(
			"Stock Entry",
			filters={"tc_source_doctype": doctype, "tc_source_name": name, "docstatus": 1},
			pluck="name",
		)
		return {
			row.item_code: row.qty for entry in names for row in frappe.get_doc("Stock Entry", entry).items
		}


@bru("BRU-INV-002")
class TestWashComplete(ProgramCase):
	def ctx(self, qty=3, result="Pass", name="WB-F42-10"):
		return {
			"batch": name,
			"equipment": self.machine.name,
			"program": self.program.name,
			"sets": ["S1", "S2"],
			"chemicals": [{"item": ITEM, "lot": self.far, "qty": qty}],
			"result": result,
		}

	def test_chemical_uses_recorded_lot_and_quantity(self):
		consume.on_wash_complete(self.ctx(qty=3))
		entry = frappe.get_all(
			"Stock Entry", filters={"tc_source_name": "WB-F42-10", "docstatus": 1}, pluck="name"
		)[0]
		chemical_rows = [row for row in self.entry_rows(entry) if row.item_code == ITEM]
		self.assertEqual([(row.batch_no, row.qty) for row in chemical_rows], [(self.far, 3)])

	def test_other_program_consumables_use_norm_times_sets(self):
		consume.on_wash_complete(self.ctx())
		# 2 bộ: 2 + 1 x 2 = 4
		self.assertEqual(self.issued("Wash Batch", "WB-F42-10")[OTHER_ITEM], 4)

	def test_zero_chemical_quantity_falls_back_to_the_norm(self):
		consume.on_wash_complete(self.ctx(qty=0))
		# 1 + 1 x 2 = 3
		self.assertEqual(self.issued("Wash Batch", "WB-F42-10")[ITEM], 3)

	def test_zero_quantity_without_any_norm_tells_accounting(self):  # FEAT-043 K13, UC-25 E2
		bare = factories.make_wash_program(self.machine.name, chemical=ITEM, consumables=[])
		ctx = {**self.ctx(qty=0), "program": bare.name}
		with patch("tracecore.inventory.consume.notification.emit") as emit:
			consume.on_wash_complete(ctx)
		self.assertEqual(self.issued("Wash Batch", "WB-F42-10"), {})
		self.assertEqual(emit.call_args.args[0], "CONSUMPTION_NO_NORM")

	def test_failed_wash_consumes_nothing(self):
		consume.on_wash_complete(self.ctx(result="Fail"))
		self.assertEqual(self.issued("Wash Batch", "WB-F42-10"), {})

	def test_running_twice_does_not_double_issue(self):
		consume.on_wash_complete(self.ctx())
		consume.on_wash_complete(self.ctx())
		self.assertEqual(stock_of(OTHER_ITEM), 96)


@bru("BRU-INV-002")
class TestLoadRelease(ProgramCase):
	def ctx(self, packs=3, name="SL-F42-1"):
		return {
			"load": name,
			"equipment": self.machine.name,
			"program": self.program.name,
			"sets": [f"S{n}" for n in range(packs)],
			"packs": [f"P{n}" for n in range(packs)],
		}

	def test_norm_times_packs_with_fefo_lots_recorded(self):
		consume.on_load_release(self.ctx(packs=3))
		# ENZ: 1 + 1 x 3 = 4 lấy từ lô hạn gần; IND: 2 + 1 x 3 = 5
		issued = self.issued("Sterilization Load", "SL-F42-1")
		self.assertEqual(issued, {ITEM: 4, OTHER_ITEM: 5})
		self.assertEqual(lot_qty(self.near), 1)

	def test_program_without_norm_issues_nothing_and_tells_accounting(self):
		bare = factories.make_wash_program(self.machine.name, consumables=[])
		ctx = {**self.ctx(), "program": bare.name}
		with patch("tracecore.inventory.consume.notification.emit") as emit:
			consume.on_load_release(ctx)
		self.assertEqual(self.issued("Sterilization Load", "SL-F42-1"), {})
		self.assertEqual(emit.call_args.args[0], "CONSUMPTION_NO_NORM")

	def test_shortage_tells_accounting_but_keeps_the_load_going(self):
		with patch("tracecore.inventory.consume.notification.emit") as emit:
			consume.on_load_release(self.ctx(packs=40))  # ENZ cần 41, kho có 15
		self.assertEqual(stock_of(ITEM), 0)
		self.assertIn("CONSUMPTION_SHORT", [call.args[0] for call in emit.call_args_list])

	def test_unexpected_error_never_breaks_the_release(self):
		with (
			patch("tracecore.inventory.consume.consume_for", side_effect=RuntimeError("boom")),
			patch("tracecore.inventory.consume.notification.emit") as emit,
		):
			consume.on_load_release(self.ctx())
		self.assertEqual(emit.call_args.args[0], "CONSUMPTION_FAILED")


class TestHooksWiring(IsolatedTestCase):
	def test_m2_events_are_wired_to_the_inventory_module(self):
		hooks = frappe.get_hooks()
		self.assertIn("tracecore.inventory.consume.on_wash_complete", hooks["tracecore_after_wash_complete"])
		self.assertIn("tracecore.inventory.consume.on_load_release", hooks["tracecore_after_load_release"])
