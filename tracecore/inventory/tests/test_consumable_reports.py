"""Vật tư dùng trong chương trình, báo cáo sử dụng vật tư và truy vết lô (A-112; FR-M6-02.4, FR-M6-07, FR-M6-08)."""

import frappe

from tracecore.core import run_consumables
from tracecore.inventory import consume, usage
from tracecore.inventory.report.consumable_lot_trace import consumable_lot_trace
from tracecore.inventory.report.consumable_usage import consumable_usage
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
]

ENZYME, PACK = "CR-ENZ", "CR-BD-PACK"


class ReportCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.ensure_stock_masters()
		factories.use_stock_company(self)
		self.lot = factories.make_chemical_batch(ENZYME, "CR-ENZ-1", expiry_days=90, qty=50).name
		self.employee = factories.make_employee().name
		self.washer = factories.make_wash_machine()
		self.wash_program = factories.make_wash_program(
			self.washer.name,
			consumables=[{"item": ENZYME, "role": "Chemical", "is_required": 1, "qty_per_load": 2}],
		)
		self.sterilizer = factories.make_sterilizer()
		self.test_program = factories.make_program(
			self.sterilizer.name,
			code="BD-" + frappe.generate_hash(length=6).upper(),
			water=20,
			program_kind="Test",
			daily_test_type="bowie_dick",
			consumables=[{"item": ENZYME, "role": "Test Pack", "is_required": 1, "qty_per_load": 1}],
		)

	def wash(self, actual):
		rows = run_consumables.rows(
			self.wash_program.name, 1, [{"item": ENZYME, "qty": actual}], True, self.employee
		)
		batch = factories.make_wash_batch(
			self.washer, self.wash_program, [factories.make_wash_ready_set()], consumables=rows
		)
		consume.on_wash_complete(
			{
				"batch": batch.name,
				"program": self.wash_program.name,
				"sets": [],
				"chemicals": [],
				"result": "Pass",
			}
		)
		return batch


class TestProgramsUsing(ReportCase):
	def test_item_lists_programs_with_stage_test_type_role_and_norm(self):
		rows = {row["program"]: row for row in usage.programs_using(ENZYME)}
		wash = rows[self.wash_program.name]
		self.assertEqual((wash["stage"], wash["role"], wash["qty_per_load"]), ("Disinfection", "Chemical", 2))
		self.assertEqual(wash["equipment"], self.washer.name)
		test = rows[self.test_program.name]
		self.assertEqual(
			(test["stage"], test["test_type"], test["role"]), ("Test", "bowie_dick", "Test Pack")
		)
		self.assertEqual(usage.programs_using("CR-NOT-USED"), [])

	def test_item_usage_rpc(self):
		from tracecore.v1 import inventory as inventory_rpc
		from tracecore.v1._common import BadRequestError

		self.assertIn(self.wash_program.name, {row["program"] for row in inventory_rpc.item_usage(ENZYME)})
		with self.assertRaises(BadRequestError):
			inventory_rpc.item_usage(None)

	def test_stage_of_runs(self):
		self.assertEqual(usage.stage("Ultrasonic Cleaner"), "Washing")
		self.assertEqual(usage.stage("Washer-Disinfector", batch_type="Manual"), "Washing")
		self.assertEqual(usage.stage("Steam Sterilizer"), "Sterilization")
		self.assertEqual(usage.stage("Steam Sterilizer", program_kind="Test"), "Test")


class TestConsumableUsage(ReportCase):
	def test_norm_actual_and_variance_per_machine_stage_and_item(self):
		self.wash(3)
		self.wash(2)
		_columns, data = consumable_usage.execute(
			{"from_date": frappe.utils.add_days(frappe.utils.today(), -1), "to_date": frappe.utils.today()}
		)
		row = next(row for row in data if row["equipment"] == self.washer.name and row["item"] == ENZYME)
		self.assertEqual(
			(row["stage"], row["runs"], row["norm_qty"], row["actual_qty"]), ("Disinfection", 2, 4, 5)
		)
		self.assertEqual(row["variance"], 1)
		self.assertEqual(row["variance_pct"], 25)

	def test_filters_and_cancelled_runs(self):
		batch = self.wash(3)
		frappe.db.set_value("Wash Batch", batch.name, "docstatus", 2)
		_columns, data = consumable_usage.execute({"item": ENZYME, "stage": "Disinfection"})
		self.assertFalse([row for row in data if row["equipment"] == self.washer.name])
		_columns, data = consumable_usage.execute({"stage": "Test", "equipment": self.washer.name})
		self.assertEqual(data, [])


class TestTicketAcceptance(ReportCase):
	"""Tiêu chí của ticket (A-112 AC-10): Bowie-Dick và một mẻ tiệt khuẩn dùng đúng lô, lô hết hạn bị chặn, tồn đúng lô
	giảm đúng số thực dùng, truy vết từ lô ra cả hai nguồn."""

	def test_bowie_dick_and_load_use_the_chosen_lot_and_trace_back(self):
		from tracecore.core import lots
		from tracecore.core.errors import BlockedError
		from tracecore.equipment import daily_test
		from tracecore.reprocessing import releasing

		expired = factories.make_chemical_batch(ENZYME, "CR-ENZ-OLD", expiry_days=-1).name
		with self.assertRaises(BlockedError) as raised:
			daily_test.start_run(
				self.sterilizer.name,
				"bowie_dick",
				"TR-005",
				self.employee,
				consumables=[{"item": ENZYME, "batch": expired}],
				consumables_confirmed=True,
			)
		self.assertEqual(raised.exception.block.code, "CONSUMABLE_LOT_INVALID")
		started = daily_test.start_run(
			self.sterilizer.name,
			"bowie_dick",
			"TR-005",
			self.employee,
			consumables=[{"item": ENZYME, "batch": self.lot}],
			consumables_confirmed=True,
		)
		daily_test.end_run(self.sterilizer.name, "bowie_dick")
		daily_test.record(
			self.sterilizer.name,
			"bowie_dick",
			"Pass",
			"TR-005",
			photo="/private/files/bd.png",
			employee=self.employee,
		)
		program = factories.make_sterilize_program(
			self.sterilizer.name, consumables=[{"item": ENZYME, "role": "Chemical", "qty_per_load": 2}]
		)
		rows = run_consumables.rows(
			program.name, 1, [{"item": ENZYME, "batch": self.lot}], True, self.employee
		)
		load = factories.make_load(
			self.sterilizer,
			program,
			[factories.make_load_ready_pack()],
			operator=self.employee,
			consumables=rows,
		)
		releasing._finalize(frappe.get_doc("Sterilization Load", load.name), None, None, self.employee, None)
		self.assertEqual(lots._stock(ENZYME)[self.lot], 47)  # 50 - 1 gói test - 2 của mẻ
		_columns, data = consumable_lot_trace.execute({"batch": self.lot})
		issued = {(row["source_type"], row["source"]): row["issued_qty"] for row in data}
		self.assertEqual(issued[("Daily Test", started["daily_test"])], 1)
		self.assertEqual(issued[("Sterilization Load", load.name)], 2)


class TestLotTrace(ReportCase):
	def test_lot_traces_to_runs_issues_and_indicator_results(self):
		batch = self.wash(2)
		load = factories.make_load(
			self.sterilizer,
			factories.make_sterilize_program(self.sterilizer.name),
			[factories.make_load_ready_pack()],
		)
		indicator = frappe.get_doc(
			{
				"doctype": "Load Indicator Result",
				"load": load.name,
				"indicator": "biological",
				"result": "Pass",
				"lot": self.lot,
				"batch": self.lot,
			}
		)
		indicator.flags.tc_releasing = True
		indicator.flags.ignore_links = True
		indicator.insert(ignore_permissions=True)
		_columns, data = consumable_lot_trace.execute({"batch": self.lot})
		by_source = {(row["source_type"], row["source"]): row for row in data}
		wash = by_source[("Wash Batch", batch.name)]
		self.assertEqual((wash["issued_qty"], wash["equipment"]), (2, self.washer.name))
		self.assertIn(("Sterilization Load", load.name), by_source)
		self.assertEqual(by_source[("Sterilization Load", load.name)]["packs"], 1)
		self.assertTrue(wash["stock_entry"])
		self.assertEqual(consumable_lot_trace.execute({})[1], [])

	def test_manual_issue_without_source_is_listed_by_its_entry(self):
		entry = consume.submit_issue(
			[consume.issue_row(ENZYME, 1, self.lot, factories.ensure_stock_masters()["warehouse"])],
			None,
			None,
			"manual",
		)
		_columns, data = consumable_lot_trace.execute({"batch": self.lot})
		self.assertIn(("Stock Entry", entry), {(row["source_type"], row["source"]) for row in data})
