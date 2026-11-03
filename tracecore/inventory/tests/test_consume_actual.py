"""Trừ kho theo số thực dùng đã xác nhận, gồm test đầu ngày (A-111; FR-M6-03, FR-M6-03.5, BRU-INV-002, BRU-INV-003)."""

import frappe
from frappe.utils import flt

from tracecore.core import run_consumables
from tracecore.equipment import daily_test
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

ENZYME, CI, TEST_PACK = "CA-ENZ", "CA-CI", "CA-BD"


def issued(source_doctype, source_name):
	entry = frappe.db.get_value(
		"Stock Entry", {"tc_source_doctype": source_doctype, "tc_source_name": source_name, "docstatus": 1}
	)
	if not entry:
		return {}
	out = {}
	for row in frappe.get_doc("Stock Entry", entry).items:
		out[row.item_code] = out.get(row.item_code, 0) + flt(row.qty)
	return out


class ActualCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.ensure_stock_masters()
		factories.use_stock_company(self)
		self.enzyme_lot = factories.make_chemical_batch(ENZYME, "CA-ENZ-1", expiry_days=90, qty=20).name
		self.ci_lot = factories.make_chemical_batch(CI, "CA-CI-1", expiry_days=90, qty=20).name
		self.pack_lot = factories.make_chemical_batch(TEST_PACK, "CA-BD-1", expiry_days=90, qty=20).name
		self.employee = factories.make_employee()


class TestWashAndLoad(ActualCase):
	def setUp(self):
		super().setUp()
		self.washer = factories.make_wash_machine()
		self.wash = factories.make_wash_program(
			self.washer.name,
			consumables=[
				{"item": ENZYME, "role": "Chemical", "is_required": 1, "qty_per_load": 2},
				{"item": CI, "role": "Chemical Indicator", "qty_per_load": 1},
			],
		)

	def wash_batch(self, rows=True):
		fields = {}
		if rows:
			fields["consumables"] = run_consumables.rows(
				self.wash.name, 1, [{"item": ENZYME, "qty": 5}], True, self.employee.name
			)
		return factories.make_wash_batch(
			self.washer,
			self.wash,
			[factories.make_wash_ready_set()],
			chemicals=[{"item": ENZYME, "lot": self.enzyme_lot, "qty": 0}],
			**fields,
		)

	def ctx(self, batch):
		return {
			"batch": batch.name,
			"program": self.wash.name,
			"sets": [],
			"chemicals": [{"item": ENZYME, "lot": self.enzyme_lot, "qty": 0}],
			"result": "Pass",
		}

	@bru("BRU-INV-002", "BRU-INV-003")
	def test_wash_issues_the_actual_quantity_not_the_indicator(self):
		batch = self.wash_batch()
		consume.on_wash_complete(self.ctx(batch))
		self.assertEqual(issued("Wash Batch", batch.name), {ENZYME: 5})
		row = next(row for row in frappe.get_doc("Wash Batch", batch.name).consumables if row.item == ENZYME)
		self.assertEqual(row.lots, f"{self.enzyme_lot}: 5")

	def test_old_batch_without_rows_uses_norms_without_indicators(self):
		batch = self.wash_batch(rows=False)
		consume.on_wash_complete(self.ctx(batch))
		self.assertEqual(issued("Wash Batch", batch.name), {ENZYME: 2})

	@bru("BRU-INV-002")
	def test_released_load_issues_the_actual_quantity(self):
		machine = factories.make_sterilizer()
		program = factories.make_sterilize_program(
			machine.name, consumables=[{"item": ENZYME, "role": "Other", "qty_per_pack": 1}]
		)
		pack = factories.make_load_ready_pack()
		rows = run_consumables.rows(program.name, 1, [{"item": ENZYME, "qty": 3}], True, self.employee.name)
		load = factories.make_load(machine, program, [pack], consumables=rows)
		consume.on_load_release({"load": load.name, "program": program.name, "packs": [pack.name]})
		self.assertEqual(issued("Sterilization Load", load.name), {ENZYME: 3})


class TestDailyTestConsumption(ActualCase):
	def setUp(self):
		super().setUp()
		self.machine = factories.make_sterilizer()
		self.bowie = factories.make_program(
			self.machine.name,
			code="BD-" + frappe.generate_hash(length=6).upper(),
			water=20,
			program_kind="Test",
			daily_test_type="bowie_dick",
			consumables=[
				{"item": TEST_PACK, "role": "Test Pack", "is_required": 1, "qty_per_load": 1},
				{"item": CI, "role": "Chemical Indicator", "qty_per_load": 1},
			],
		)

	def run_test(self, lot):
		started = daily_test.start_run(
			self.machine.name,
			"bowie_dick",
			"TR-005",
			self.employee.name,
			consumables=[{"item": TEST_PACK, "qty": 1}],
			consumables_confirmed=True,
		)
		daily_test.end_run(self.machine.name, "bowie_dick")
		daily_test.record(
			self.machine.name,
			"bowie_dick",
			"Pass",
			"TR-005",
			lot=lot,
			lot_expiry=frappe.utils.add_days(frappe.utils.today(), 30),
			photo="/private/files/bd.png",
			employee=self.employee.name,
		)
		return started["daily_test"]

	@bru("BRU-INV-003")
	def test_recording_the_result_issues_the_test_pack_from_the_entered_lot(self):
		name = self.run_test(self.pack_lot)
		self.assertEqual(issued("Daily Test", name), {TEST_PACK: 1})
		entry = frappe.db.get_value("Stock Entry", {"tc_source_name": name, "docstatus": 1})
		self.assertEqual(frappe.get_doc("Stock Entry", entry).items[0].batch_no, self.pack_lot)

	def test_free_text_lot_falls_back_to_fefo_and_retry_does_not_issue_twice(self):
		name = self.run_test("LOT-ON-THE-BOX")
		self.assertEqual(issued("Daily Test", name), {TEST_PACK: 1})
		self.assertFalse(consume.retry("Daily Test", name)["created"])
