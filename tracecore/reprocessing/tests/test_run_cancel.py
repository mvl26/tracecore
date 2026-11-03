"""R02 hủy lô rửa / mẻ tiệt khuẩn nhập sai (A-112 D10, D11; FR-M2-03.10, FR-M2-09.10, FR-M6-03.9, BRU-REP-018)."""

from unittest.mock import patch

import frappe
from frappe.utils import cint, flt

from tracecore.core import lots, run_consumables, step_gate
from tracecore.core.errors import BlockedError
from tracecore.costing import sheet
from tracecore.instrument import maintenance
from tracecore.inventory import consume
from tracecore.reprocessing import releasing, run_cancel, washing
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
	"Department",
	"User",
	"Employee",
]

ENZYME = "RC-ENZ"
REASON = "Nhập nhầm máy"


def gate(set_unit, step):
	return next(row["result"] for row in step_gate.gates(set_unit) if row["step"] == step)


def lot_qty(batch):
	return flt(lots._stock(ENZYME).get(batch, 0))


def entry_of(doctype, name):
	return frappe.db.get_value(
		"Stock Entry",
		{"tc_source_doctype": doctype, "tc_source_name": name},
		["name", "docstatus"],
		as_dict=True,
	)


class CancelCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.ensure_stock_masters()
		factories.use_stock_company(self)
		self.lot = factories.make_chemical_batch(ENZYME, "RC-ENZ-1", expiry_days=90, qty=20).name
		self.employee = factories.make_employee().name

	def assert_blocked(self, fn, *args):
		with self.assertRaises(BlockedError) as raised:
			fn(*args)
		self.assertEqual(raised.exception.block.code, "RUN_CANCEL_BLOCKED")
		return raised.exception.block


class TestCancelWash(CancelCase):
	def setUp(self):
		super().setUp()
		self.washer = factories.make_wash_machine()
		self.program = factories.make_wash_program(
			self.washer.name, consumables=[{"item": ENZYME, "role": "Chemical", "qty_per_load": 3}]
		)
		self.set_unit = factories.make_wash_ready_set().name
		rows = run_consumables.rows(self.program.name, 1, [], True, self.employee)
		self.batch = factories.make_wash_batch(
			self.washer,
			self.program,
			[self.set_unit],
			operator=self.employee,
			consumables=rows,
			status=washing.RUNNING,
		)

	def pass_batch(self):
		step_gate.record(self.set_unit, "T2", "Pass", "Wash Batch", self.batch.name)
		doc = frappe.get_doc("Wash Batch", self.batch.name)
		doc.update({"status": "Passed", "cycle_result": "Pass", "ended_at": frappe.utils.now_datetime()})
		doc.flags.tc_washing = True
		doc.submit()
		consume.on_wash_complete(consume.wash_context(doc.name))
		return doc

	def test_running_batch_is_closed_and_its_sets_can_be_loaded_again(self):
		self.assertEqual(washing._running_batch_of(self.set_unit), self.batch.name)
		run_cancel.cancel_wash(self.batch.name, REASON, self.employee)
		doc = frappe.get_doc("Wash Batch", self.batch.name)
		self.assertEqual((doc.docstatus, doc.cancel_reason, doc.cancelled_by), (2, REASON, self.employee))
		self.assertIsNone(washing._running_batch_of(self.set_unit))

	@bru("BRU-REP-018")
	def test_passed_batch_reverts_t2_and_cancels_its_issue(self):
		self.pass_batch()
		self.assertEqual(lot_qty(self.lot), 17)
		run_cancel.cancel_wash(self.batch.name, REASON, self.employee)
		self.assertEqual(gate(self.set_unit, "T2"), "Pending")
		self.assertEqual(frappe.db.get_value("Set Unit", self.set_unit, "status"), "Processing")
		self.assertEqual(entry_of("Wash Batch", self.batch.name).docstatus, 2)
		self.assertEqual(lot_qty(self.lot), 20)
		self.assertEqual(frappe.db.get_value("Wash Batch", self.batch.name, "docstatus"), 2)

	@bru("BRU-REP-018")
	def test_batch_whose_set_reached_assembly_is_refused(self):
		self.pass_batch()
		step_gate.record(self.set_unit, "T3", "Pass", None, None)
		block = self.assert_blocked(run_cancel.cancel_wash, self.batch.name, REASON, self.employee)
		self.assertIn(self.set_unit, block.items)
		self.assertEqual(gate(self.set_unit, "T2"), "Pass")

	def test_failed_or_already_cancelled_batch_and_missing_reason_are_refused(self):
		frappe.db.set_value("Wash Batch", self.batch.name, "status", "Failed")
		self.assert_blocked(run_cancel.cancel_wash, self.batch.name, REASON, self.employee)
		frappe.db.set_value("Wash Batch", self.batch.name, {"status": washing.RUNNING, "docstatus": 2})
		self.assert_blocked(run_cancel.cancel_wash, self.batch.name, REASON, self.employee)
		with self.assertRaises(BlockedError) as raised:
			run_cancel.cancel_wash(self.batch.name, "  ", self.employee)
		self.assertEqual(raised.exception.block.code, "REASON_REQUIRED")

	def test_draft_issue_blocks_the_cancel(self):
		self.pass_batch()
		entry = entry_of("Wash Batch", self.batch.name).name
		frappe.get_doc("Stock Entry", entry).cancel()
		draft = frappe.copy_doc(frappe.get_doc("Stock Entry", entry))
		draft.update({"docstatus": 0, "amended_from": None})
		for row in draft.items:
			row.docstatus = 0
		draft.insert(ignore_permissions=True)
		self.assert_blocked(run_cancel.cancel_wash, self.batch.name, REASON, self.employee)

	def test_rpc_answers_with_a_body(self):
		from tracecore.v1 import wash as wash_rpc

		frappe.db.set_value("Wash Batch", self.batch.name, "status", "Failed")
		self.assertFalse(wash_rpc.cancel(self.batch.name, REASON)["ok"])
		frappe.db.set_value("Wash Batch", self.batch.name, "status", washing.RUNNING)
		self.assertEqual(wash_rpc.cancel(self.batch.name, REASON)["sets"], [self.set_unit])

	def test_only_r02_may_cancel(self):
		with patch.object(frappe, "get_roles", return_value=["TC R03"]):
			with self.assertRaises(frappe.PermissionError):
				run_cancel.cancel_wash(self.batch.name, REASON, self.employee)


class TestCancelLoad(CancelCase):
	def setUp(self):
		super().setUp()
		self.machine = factories.make_sterilizer()
		self.program = factories.make_sterilize_program(
			self.machine.name, consumables=[{"item": ENZYME, "role": "Chemical", "qty_per_load": 2}]
		)
		self.pack = factories.make_load_ready_pack()
		self.set_unit = self.pack.set_unit
		rows = run_consumables.rows(self.program.name, 1, [], True, self.employee)
		self.load = factories.make_load(
			self.machine, self.program, [self.pack], operator=self.employee, consumables=rows
		)

	def release(self):
		doc = frappe.get_doc("Sterilization Load", self.load.name)
		releasing._finalize(doc, None, None, self.employee, None)
		return doc

	def test_running_load_returns_its_packs_to_loading(self):
		run_cancel.cancel_load(self.load.name, REASON, self.employee)
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, ["status", "load"]), ("Packed", None))
		self.assertEqual(frappe.db.get_value("Sterilization Load", self.load.name, "docstatus"), 2)

	@bru("BRU-REP-018")
	def test_released_load_reverts_t5_cycle_count_issue_and_cost_sheet(self):
		cycles = cint(frappe.db.get_value("Set Unit", self.set_unit, "cycles_used"))
		self.release()
		sheet.build("Sterilization Load", self.load.name)
		self.assertEqual(gate(self.set_unit, "T5"), "Pass")
		self.assertEqual(lot_qty(self.lot), 18)
		run_cancel.cancel_load(self.load.name, REASON, self.employee)
		self.assertEqual(gate(self.set_unit, "T5"), "Pending")
		unit = frappe.db.get_value("Set Unit", self.set_unit, ["status", "cycles_used"], as_dict=True)
		self.assertEqual((unit.status, cint(unit.cycles_used)), ("Processing", cycles))
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, ["status", "load"]), ("Packed", None))
		self.assertEqual(lot_qty(self.lot), 20)
		self.assertEqual(
			frappe.db.get_value("Cost Sheet", {"source_name": self.load.name}, "status"), "Cancelled"
		)

	@bru("BRU-REP-018")
	def test_load_with_a_pack_in_sterile_stock_is_refused(self):
		self.release()
		frappe.db.set_value("Pack", self.pack.name, "status", "In Sterile Stock")
		block = self.assert_blocked(run_cancel.cancel_load, self.load.name, REASON, self.employee)
		self.assertIn(self.pack.name, block.items)
		self.assertEqual(gate(self.set_unit, "T5"), "Pass")

	def test_failed_load_is_refused(self):
		frappe.db.set_value("Sterilization Load", self.load.name, "status", "Failed")
		self.assert_blocked(run_cancel.cancel_load, self.load.name, REASON, self.employee)

	def test_rpc_answers_with_a_body(self):
		from tracecore.v1 import load as load_rpc

		self.assertFalse(load_rpc.cancel(self.load.name, " ")["ok"])
		self.assertEqual(load_rpc.cancel(self.load.name, REASON)["packs"], [self.pack.name])


class TestMaintenanceCounter(IsolatedTestCase):
	def test_cancelled_release_takes_back_the_count_of_that_cycle_id(self):
		set_unit = factories.make_set_unit().name
		instrument = factories.make_instrument(
			"RC-INS-" + frappe.generate_hash(length=5).upper(), interval=10
		)
		row = frappe.get_doc(
			{
				"doctype": "Instrument Maintenance",
				"set_unit": set_unit,
				"instrument": getattr(instrument, "name", instrument),
				"cycles_since_maint": 3,
				"last_release_cycle": "CY-RC-1",
			}
		)
		row.flags.tc_maintenance = True
		row.insert(ignore_permissions=True)
		maintenance.on_release_cancelled({"set_unit": set_unit, "cycle_id": "CY-OTHER"})
		self.assertEqual(frappe.db.get_value("Instrument Maintenance", row.name, "cycles_since_maint"), 3)
		maintenance.on_release_cancelled({"set_unit": set_unit, "cycle_id": "CY-RC-1"})
		self.assertEqual(
			frappe.db.get_value(
				"Instrument Maintenance", row.name, ["cycles_since_maint", "last_release_cycle"]
			),
			(2, None),
		)
