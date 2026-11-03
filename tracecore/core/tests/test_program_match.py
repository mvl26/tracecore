"""Chương trình theo máy của loại bộ (A-110, ticket #1865; FR-M1-03.7, FR-M1-03.8, FR-M5-02.5, BRU-REP-017)."""

import frappe

from tracecore.core import program_match
from tracecore.core.errors import BlockedError
from tracecore.tests.factories import (
	make_program,
	make_set_type,
	make_sterilize_program,
	make_sterilizer,
	make_wash_machine,
	make_wash_program,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def type_code():
	return "PM" + frappe.generate_hash(length=4).upper()


def set_type(method="Steam"):
	return make_set_type(type_code(), method=method)


def link(set_type_doc, *rows):
	"""Ghi bảng Chương trình theo máy như R10 lưu trên Desk; `rows` là ``(chương trình, mặc định)``."""
	doc = frappe.get_doc("Instrument Set Type", set_type_doc.name)
	doc.set("programs", [{"program": program.name, "is_default": int(default)} for program, default in rows])
	doc.save()
	return doc


def set_control(level):
	frappe.db.set_single_value("TraceCore Settings", "program_control", level)


class ProgramMatchCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.washer = make_wash_machine()
		self.wash_a = make_wash_program(self.washer.name, program_name="A Rửa 55 độ")
		self.wash_b = make_wash_program(self.washer.name, program_name="B Rửa MIS")
		self.steam = make_sterilizer()
		self.steam_134 = make_sterilize_program(self.steam.name, program_name="Hấp 134")
		self.plasma = make_sterilizer(equipment_type="Plasma Sterilizer")
		self.plasma_std = make_sterilize_program(self.plasma.name, program_name="Plasma chuẩn")


class TestSetTypeRows(ProgramMatchCase):
	@bru("BRU-REP-017")
	def test_row_takes_machine_and_stage_from_program(self):
		doc = link(set_type(), (self.wash_a, True), (self.steam_134, True))
		rows = {row.program: row for row in doc.programs}
		self.assertEqual(rows[self.wash_a.name].equipment, self.washer.name)
		self.assertEqual(rows[self.wash_a.name].stage, "Washer-Disinfection")
		self.assertEqual(rows[self.steam_134.name].equipment, self.steam.name)
		self.assertEqual(rows[self.steam_134.name].stage, "Sterilization")

	def test_ultrasonic_stage(self):
		cleaner = make_wash_machine(equipment_type="Ultrasonic Cleaner")
		program = make_wash_program(cleaner.name)
		doc = link(set_type(), (program, True))
		self.assertEqual(doc.programs[0].stage, "Ultrasonic Washing")

	@bru("BRU-REP-017")
	def test_two_defaults_for_one_machine_are_refused(self):
		with self.assertRaises(frappe.ValidationError) as raised:
			link(set_type(), (self.wash_a, True), (self.wash_b, True))
		self.assertIn(self.washer.name, str(raised.exception))

	def test_several_allowed_programs_and_one_default_per_machine(self):
		doc = link(set_type(), (self.wash_a, True), (self.wash_b, False), (self.steam_134, True))
		self.assertEqual(len(doc.programs), 3)

	@bru("BRU-REP-004", "BRU-REP-017")
	def test_sterilize_program_must_match_set_method(self):
		with self.assertRaises(frappe.ValidationError):
			link(set_type("Plasma"), (self.steam_134, True))
		with self.assertRaises(frappe.ValidationError):
			link(set_type("Steam"), (self.plasma_std, True))
		link(set_type("Plasma"), (self.plasma_std, True))

	def test_test_inactive_duplicate_and_foreign_machines_are_refused(self):
		bowie = make_program(
			self.steam.name, code="BD-" + frappe.generate_hash(length=5), program_kind="Test"
		)
		inactive = make_wash_program(self.washer.name)
		frappe.db.set_value("Process Program", inactive.name, "is_active", 0)
		sealer = make_wash_machine(equipment_type="Sealer")
		sealing = make_program(sealer.name, code="HT-" + frappe.generate_hash(length=5))
		for rows in (
			((bowie, False),),
			((inactive, False),),
			((sealing, False),),
			((self.wash_a, True), (self.wash_a, False)),
		):
			with self.assertRaises(frappe.ValidationError):
				link(set_type(), *rows)


class TestMachineMapAndFit(ProgramMatchCase):
	def setUp(self):
		super().setUp()
		self.ortho = link(set_type(), (self.wash_a, True), (self.wash_b, False))
		self.micro = link(set_type(), (self.wash_b, True))
		self.plain = set_type()

	def test_machine_map_lists_default_and_allowed(self):
		mapping = program_match.machine_map(self.washer.name)
		self.assertEqual(
			mapping[self.ortho.name],
			{"default": self.wash_a.name, "allowed": [self.wash_a.name, self.wash_b.name]},
		)
		self.assertEqual(
			mapping[self.micro.name], {"default": self.wash_b.name, "allowed": [self.wash_b.name]}
		)
		self.assertNotIn(self.plain.name, mapping)
		self.assertEqual(program_match.machine_map(self.steam.name), {})

	def test_inactive_program_leaves_the_map(self):
		frappe.db.set_value("Process Program", self.wash_b.name, "is_active", 0)
		mapping = program_match.machine_map(self.washer.name)
		self.assertEqual(mapping[self.ortho.name]["allowed"], [self.wash_a.name])
		self.assertNotIn(self.micro.name, mapping)

	@bru("BRU-REP-017")
	def test_fit(self):
		self.assertEqual(program_match.fit(self.ortho.name, self.washer.name, self.wash_a.name), "Default")
		self.assertEqual(program_match.fit(self.ortho.name, self.washer.name, self.wash_b.name), "Allowed")
		self.assertEqual(program_match.fit(self.micro.name, self.washer.name, self.wash_a.name), "Outside")
		self.assertEqual(program_match.fit(self.plain.name, self.washer.name, self.wash_a.name), "Unmapped")

	def test_suggest_single_default(self):
		mapping = program_match.machine_map(self.washer.name)
		result = program_match.suggest([self.ortho.name, self.plain.name], mapping)
		self.assertEqual(result["program"], self.wash_a.name)
		self.assertFalse(result["conflict"])

	def test_suggest_common_program_when_defaults_differ(self):
		mapping = program_match.machine_map(self.washer.name)
		result = program_match.suggest([self.ortho.name, self.micro.name], mapping)
		self.assertTrue(result["conflict"])
		self.assertEqual(result["common"], [self.wash_b.name])
		self.assertEqual(result["program"], self.wash_b.name)

	def test_suggest_split_when_no_common_program(self):
		third = link(set_type(), (self.wash_a, True))
		mapping = program_match.machine_map(self.washer.name)
		result = program_match.suggest([third.name, self.micro.name], mapping)
		self.assertTrue(result["conflict"])
		self.assertEqual(result["common"], [])

	def test_suggest_without_mapping(self):
		result = program_match.suggest([self.plain.name], program_match.machine_map(self.washer.name))
		self.assertEqual(result, {"program": None, "conflict": False, "common": [], "defaults": {}})


class TestControlLevel(ProgramMatchCase):
	def setUp(self):
		super().setUp()
		self.micro = link(set_type(), (self.wash_b, True))

	def test_default_level_is_warn(self):
		frappe.db.set_single_value("TraceCore Settings", "program_control", None)
		self.assertEqual(program_match.control_level(), "Warn")

	@bru("BRU-REP-017")
	def test_admit_blocks_outside_only_at_block_level(self):
		set_control("Warn")
		self.assertEqual(
			program_match.admit(self.micro.name, self.washer.name, self.wash_a.name)["fit"], "Outside"
		)
		set_control("Override")
		self.assertEqual(
			program_match.admit(self.micro.name, self.washer.name, self.wash_a.name)["fit"], "Outside"
		)
		set_control("Block")
		with self.assertRaises(BlockedError) as raised:
			program_match.admit(self.micro.name, self.washer.name, self.wash_a.name)
		self.assertEqual(raised.exception.block.code, "PROGRAM_NOT_FOR_SET")
		self.assertEqual(raised.exception.block.http_status, 422)
		admitted = program_match.admit(self.micro.name, self.washer.name, self.wash_b.name)
		self.assertEqual(admitted, {"fit": "Default", "default": self.wash_b.name})

	@bru("BRU-REP-017")
	def test_review_records_override(self):
		set_control("Warn")
		fields = program_match.review([self.micro.name], self.washer.name, self.wash_a.name, "HR-EMP-1")
		self.assertEqual(
			fields,
			{
				"suggested_program": self.wash_b.name,
				"program_override_by": "HR-EMP-1",
				"program_override_reason": None,
			},
		)
		fields = program_match.review([self.micro.name], self.washer.name, self.wash_b.name, "HR-EMP-1")
		self.assertIsNone(fields["program_override_by"])

	@bru("BRU-REP-017")
	def test_override_level_needs_a_reason(self):
		set_control("Override")
		with self.assertRaises(BlockedError) as raised:
			program_match.review([self.micro.name], self.washer.name, self.wash_a.name, "HR-EMP-1", "  ")
		self.assertEqual(raised.exception.block.code, "PROGRAM_OVERRIDE_REASON_REQUIRED")
		fields = program_match.review(
			[self.micro.name], self.washer.name, self.wash_a.name, "HR-EMP-1", " Bộ cần rửa kỹ "
		)
		self.assertEqual(fields["program_override_reason"], "Bộ cần rửa kỹ")


class TestProgramSetTypes(ProgramMatchCase):
	def test_program_lists_set_types_using_it(self):
		ortho = link(set_type(), (self.steam_134, True))
		rows = program_match.set_types_of(self.steam_134.name)
		self.assertEqual(
			[(row["set_type"], row["is_default"], row["mismatch"]) for row in rows], [(ortho.name, 1, 0)]
		)
		frappe.db.set_value("Instrument Set Type", ortho.name, "method", "Plasma")
		self.assertEqual(program_match.set_types_of(self.steam_134.name)[0]["mismatch"], 1)
