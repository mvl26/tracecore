"""Vật tư theo chương trình (A-111; FR-M5-02.6, FR-M5-02.7, FR-M5-02.8, FR-M6-03.5, BRU-INV-003)."""

import frappe

from tracecore.core import run_consumables
from tracecore.core.errors import BlockedError
from tracecore.equipment import programs
from tracecore.equipment.report.program_consumable_gaps import program_consumable_gaps as gaps
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

ENZYME, LABEL, CI, TEST_PACK = "RC-ENZ", "RC-LBL", "RC-CI", "RC-BD"


def code(prefix):
	return prefix + "-" + frappe.generate_hash(length=6).upper()


def blocked(case, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


def test_program(equipment, test_type="bowie_dick", consumables=None):
	return factories.make_program(
		equipment,
		code=code("BD"),
		water=20,  # máy hấp dùng nước: thiếu nước thì định mức Thiếu (A-04 Q1)
		program_kind="Test",
		daily_test_type=test_type,
		consumables=consumables
		if consumables is not None
		else [{"item": TEST_PACK, "role": "Test Pack", "is_required": 1, "qty_per_load": 1}],
	)


class ConsumablesCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.make_item(ENZYME, "Chemical")
		factories.make_item(LABEL, "Label")
		factories.make_item(CI, "Chemical Indicator")
		factories.make_item(TEST_PACK, "Test")
		self.washer = factories.make_wash_machine()
		self.wash = factories.make_wash_program(
			self.washer.name,
			consumables=[
				{
					"item": ENZYME,
					"role": "Chemical",
					"is_required": 1,
					"qty_per_load": 2,
					"qty_per_pack": 0.5,
				},
				{"item": LABEL, "role": "Label", "qty_per_load": 1},
				{"item": CI, "role": "Chemical Indicator", "is_required": 1, "qty_per_load": 1},
			],
		)


class TestLines(ConsumablesCase):
	def test_role_and_required_are_saved(self):
		rows = {row.item: row for row in frappe.get_doc("Process Program", self.wash.name).consumables}
		self.assertEqual((rows[ENZYME].role, rows[ENZYME].is_required), ("Chemical", 1))
		self.assertEqual((rows[LABEL].role, rows[LABEL].is_required), ("Label", 0))

	def test_lines_scale_with_sets_and_mark_indicators_not_issued(self):
		lines = {line["item"]: line for line in run_consumables.lines_of(self.wash.name, units=4)}
		self.assertEqual(lines[ENZYME]["norm_qty"], 4)
		self.assertEqual(lines[LABEL]["norm_qty"], 1)
		self.assertEqual((lines[ENZYME]["issued"], lines[CI]["issued"]), (1, 0))
		self.assertEqual(lines[ENZYME]["uom"], "Nos")

	def test_payload_carries_factors_for_the_station(self):
		line = next(row for row in run_consumables.payload(self.wash.name) if row["item"] == ENZYME)
		self.assertEqual((line["per_load"], line["per_pack"], line["is_required"]), (2, 0.5, 1))
		self.assertNotIn("norm_qty", line)


class TestRows(ConsumablesCase):
	@bru("BRU-INV-003")
	def test_required_items_need_confirmation(self):
		block = blocked(self, run_consumables.rows, self.wash.name, 2, None, False, "HR-EMP-1")
		self.assertEqual(block.code, "CONSUMABLES_NOT_CONFIRMED")
		self.assertEqual(block.http_status, 422)

	@bru("BRU-INV-003")
	def test_required_item_with_zero_quantity_is_refused(self):
		block = blocked(
			self, run_consumables.rows, self.wash.name, 2, [{"item": ENZYME, "qty": 0}], True, "HR-EMP-1"
		)
		self.assertEqual(block.code, "CONSUMABLES_NOT_CONFIRMED")
		self.assertIn(ENZYME, block.reason)

	def test_unknown_item_or_negative_quantity_is_refused(self):
		for given in (
			[{"item": "RC-OTHER", "qty": 1}],
			[{"item": LABEL, "qty": -1}],
			[{"item": LABEL, "qty": "x"}],
		):
			block = blocked(self, run_consumables.rows, self.wash.name, 2, given, True, "HR-EMP-1")
			self.assertEqual(block.code, "CONSUMABLE_INVALID")

	@bru("BRU-INV-003")
	def test_rows_keep_norm_actual_and_who_confirmed(self):
		rows = run_consumables.rows(self.wash.name, 2, [{"item": ENZYME, "qty": 5}], True, "HR-EMP-1")
		by_item = {row["item"]: row for row in rows}
		self.assertEqual((by_item[ENZYME]["norm_qty"], by_item[ENZYME]["actual_qty"]), (3, 5))
		self.assertEqual(by_item[LABEL]["actual_qty"], 1)  # không sửa = định mức
		self.assertEqual(by_item[ENZYME]["confirmed_by"], "HR-EMP-1")
		self.assertTrue(by_item[ENZYME]["confirmed_at"])

	def test_program_without_required_items_needs_no_confirmation(self):
		plain = factories.make_wash_program(
			self.washer.name, consumables=[{"item": LABEL, "role": "Label", "qty_per_load": 1}]
		)
		rows = run_consumables.rows(plain.name, 1, None, False, "HR-EMP-1")
		self.assertEqual(
			[(row["item"], row["actual_qty"], row["confirmed_by"]) for row in rows], [(LABEL, 1, None)]
		)
		self.assertEqual(
			run_consumables.rows(factories.make_wash_program(self.washer.name).name, 1, None, False), []
		)


class TestIssueLines(ConsumablesCase):
	def batch(self):
		rows = run_consumables.rows(self.wash.name, 2, [{"item": ENZYME, "qty": 5}], True, "HR-EMP-1")
		return factories.make_wash_batch(
			self.washer, self.wash, [factories.make_wash_ready_set()], consumables=rows
		)

	@bru("BRU-INV-003")
	def test_issue_lines_use_actual_skip_indicators_and_pin_lots(self):
		batch = self.batch()
		lines = run_consumables.issue_lines("Wash Batch", batch.name, {ENZYME: "LOT-1"})
		self.assertEqual(
			lines, [{"item": ENZYME, "qty": 5, "batch": "LOT-1"}, {"item": LABEL, "qty": 1, "batch": None}]
		)

	def test_no_rows_means_legacy(self):
		batch = factories.make_wash_batch(self.washer, self.wash, [factories.make_wash_ready_set()])
		self.assertIsNone(run_consumables.issue_lines("Wash Batch", batch.name))

	def test_lots_are_written_back(self):
		batch = self.batch()
		run_consumables.record_lots(
			"Wash Batch",
			batch.name,
			[{"item": ENZYME, "batch": "LOT-1", "qty": 3}, {"item": ENZYME, "batch": "LOT-2", "qty": 2}],
		)
		rows = {row.item: row for row in frappe.get_doc("Wash Batch", batch.name).consumables}
		self.assertEqual(rows[ENZYME].lots, "LOT-1: 3, LOT-2: 2")
		self.assertFalse(rows[LABEL].lots)


class TestTestPrograms(ConsumablesCase):
	def setUp(self):
		super().setUp()
		self.steam = factories.make_sterilizer()

	def test_daily_test_type_must_fit_the_machine(self):
		self.assertEqual(test_program(self.steam.name, "leak").daily_test_type, "leak")
		with self.assertRaises(frappe.ValidationError):
			test_program(self.steam.name, "plasma_daily")
		regular = factories.make_sterilize_program(self.steam.name, daily_test_type="bowie_dick")
		self.assertFalse(regular.daily_test_type)

	def test_test_program_without_required_test_pack_has_missing_norms(self):
		self.assertEqual(test_program(self.steam.name).norm_status, "Complete")
		loose = test_program(
			self.steam.name, consumables=[{"item": TEST_PACK, "role": "Test Pack", "qty_per_load": 1}]
		)
		self.assertEqual(loose.norm_status, "Missing")


class TestCopyAndReport(ConsumablesCase):
	def setUp(self):
		super().setUp()
		self.steam = factories.make_sterilizer()
		self.other = factories.make_sterilizer()
		self.source = test_program(
			self.steam.name,
			consumables=[
				{"item": TEST_PACK, "role": "Test Pack", "is_required": 1, "qty_per_load": 1},
				{"item": LABEL, "role": "Label", "qty_per_load": 2},
			],
		)
		self.target = test_program(self.other.name)

	def test_candidates_are_same_kind_and_machine_type(self):
		names = [row["program"] for row in programs.consumable_targets(self.source.name)]
		self.assertIn(self.target.name, names)
		self.assertNotIn(self.source.name, names)
		self.assertNotIn(self.wash.name, names)

	def test_copy_replaces_the_consumables_of_the_targets(self):
		programs.copy_consumables(self.source.name, [self.target.name])
		rows = [
			(row.item, row.role, row.is_required, row.qty_per_load)
			for row in frappe.get_doc("Process Program", self.target.name).consumables
		]
		self.assertEqual(rows, [(TEST_PACK, "Test Pack", 1, 1), (LABEL, "Label", 0, 2)])

	def test_copy_to_another_kind_or_machine_type_is_refused(self):
		regular = factories.make_sterilize_program(self.other.name)
		for target in (regular.name, self.wash.name, self.source.name):
			with self.assertRaises(frappe.ValidationError):
				programs.copy_consumables(self.source.name, [target])

	def test_report_lists_programs_with_gaps(self):
		empty = factories.make_wash_program(self.washer.name)
		untyped = test_program(self.steam.name, test_type=None)
		_columns, data = gaps.execute({})
		issues = {}
		for row in data:
			issues.setdefault(row["program"], []).append(row["issue_code"])
		self.assertIn(gaps.NO_CONSUMABLES, issues[empty.name])
		self.assertIn(gaps.NO_TEST_TYPE, issues[untyped.name])
		self.assertNotIn(self.source.name, issues)
