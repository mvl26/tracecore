"""Xác nhận vật tư của chương trình ở T2, T5, test đầu ngày (A-111; FR-M2-03.9, FR-M2-09.9, FR-M5-05.5, BRU-INV-003)."""

import frappe

from tracecore.core import client_time
from tracecore.core.errors import BlockedError
from tracecore.equipment import daily_test
from tracecore.reprocessing import sterilizing, washing
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

WASH_STATION, LOAD_STATION = "TR-002", "TR-005"
ENZYME, LABEL, TEST_PACK = "RS-ENZ", "RS-LBL", "RS-BD"


def blocked(case, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


class StationCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.make_item(ENZYME, "Chemical")
		factories.make_item(LABEL, "Label")
		factories.make_item(TEST_PACK, "Test")
		self.employee = factories.make_employee()


class TestWash(StationCase):
	def setUp(self):
		super().setUp()
		self.washer = factories.make_wash_machine()
		self.program = factories.make_wash_program(
			self.washer.name,
			consumables=[
				{"item": ENZYME, "role": "Chemical", "is_required": 1, "qty_per_load": 1, "qty_per_pack": 1},
				{"item": LABEL, "role": "Label", "qty_per_load": 1},
			],
		)

	def start(self, units, **kwargs):
		return washing.start(
			self.washer.name,
			self.program.name,
			[unit.name for unit in units],
			[],
			WASH_STATION,
			client_time.utc_now(),
			self.employee.name,
			**kwargs,
		)

	def test_scan_lists_the_consumables_of_each_program(self):
		program = next(
			row
			for row in washing.scan_machine(self.washer.name)["programs"]
			if row["program_code"] == self.program.name
		)
		self.assertEqual([line["item"] for line in program["consumables"]], [ENZYME, LABEL])

	@bru("BRU-INV-003")
	def test_complete_loading_needs_confirmed_required_items(self):
		unit = factories.make_wash_ready_set()
		block = blocked(self, self.start, [unit])
		self.assertEqual(block.code, "CONSUMABLES_NOT_CONFIRMED")
		self.assertFalse(frappe.db.exists("Wash Batch Set Unit", {"set_unit": unit.name}))

	@bru("BRU-INV-003")
	def test_batch_keeps_norm_and_actual_per_accepted_sets(self):
		units = [factories.make_wash_ready_set(), factories.make_wash_ready_set()]
		result = self.start(units, consumables=[{"item": ENZYME, "qty": 4}], consumables_confirmed=True)
		rows = {row.item: row for row in frappe.get_doc("Wash Batch", result["batch"]).consumables}
		self.assertEqual((rows[ENZYME].norm_qty, rows[ENZYME].actual_qty), (3, 4))
		self.assertEqual((rows[LABEL].norm_qty, rows[LABEL].actual_qty), (1, 1))
		self.assertEqual(rows[ENZYME].confirmed_by, self.employee.name)


class TestLoad(StationCase):
	def setUp(self):
		super().setUp()
		self.machine = factories.make_sterilizer()
		self.program = factories.make_sterilize_program(
			self.machine.name,
			consumables=[{"item": LABEL, "role": "Label", "is_required": 1, "qty_per_pack": 1}],
		)

	def complete(self, packs, **kwargs):
		return sterilizing.complete(
			self.machine.name,
			self.program.name,
			[pack.name for pack in packs],
			LOAD_STATION,
			client_time.utc_now(),
			self.employee.name,
			**kwargs,
		)

	def test_scan_lists_the_consumables(self):
		program = sterilizing.scan_machine(self.machine.name)["programs"][0]
		self.assertEqual(program["consumables"][0]["item"], LABEL)

	@bru("BRU-INV-003")
	def test_load_needs_confirmation_then_keeps_rows(self):
		packs = [factories.make_load_ready_pack(), factories.make_load_ready_pack()]
		self.assertEqual(blocked(self, self.complete, packs).code, "CONSUMABLES_NOT_CONFIRMED")
		self.assertEqual(frappe.db.get_value("Pack", packs[0].name, "status"), "Packed")
		load = self.complete(packs, consumables_confirmed=True)["load"]
		row = frappe.get_doc("Sterilization Load", load).consumables[0]
		self.assertEqual((row.item, row.norm_qty, row.actual_qty), (LABEL, 2, 2))


class TestDailyTest(StationCase):
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
				{"item": LABEL, "role": "Label", "qty_per_load": 1},
			],
		)

	def test_overview_shows_the_test_program_and_its_consumables(self):
		row = next(row for row in daily_test.overview() if row.name == self.machine.name)
		entry = row["test_programs"]["bowie_dick"]
		self.assertEqual(entry["program"], self.bowie.name)
		self.assertEqual([line["item"] for line in entry["consumables"]], [TEST_PACK, LABEL])
		self.assertNotIn("leak", row["test_programs"])

	@bru("BRU-INV-003")
	def test_start_needs_confirmation_and_keeps_program_and_rows(self):
		block = blocked(
			self, daily_test.start_run, self.machine.name, "bowie_dick", LOAD_STATION, self.employee.name
		)
		self.assertEqual(block.code, "CONSUMABLES_NOT_CONFIRMED")
		started = daily_test.start_run(
			self.machine.name,
			"bowie_dick",
			LOAD_STATION,
			self.employee.name,
			consumables=[{"item": TEST_PACK, "qty": 1}],
			consumables_confirmed=True,
		)
		doc = frappe.get_doc("Daily Test", started["daily_test"])
		self.assertEqual(doc.program, self.bowie.name)
		self.assertEqual(
			[(row.item, row.actual_qty) for row in doc.consumables], [(TEST_PACK, 1), (LABEL, 1)]
		)

	def test_test_without_program_needs_nothing(self):
		started = daily_test.start_run(self.machine.name, "leak", LOAD_STATION, self.employee.name)
		doc = frappe.get_doc("Daily Test", started["daily_test"])
		self.assertFalse(doc.program)
		self.assertEqual(doc.consumables, [])
