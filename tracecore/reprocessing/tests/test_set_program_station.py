"""Chương trình theo máy của loại bộ tại T2, T5 (A-110, ticket #1865; FR-M2-03.7/.8, FR-M2-09.7/.8, BRU-REP-017)."""

import frappe

from tracecore.core import client_time
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import sterilizing, washing
from tracecore.tests.factories import (
	make_employee,
	make_load_ready_pack,
	make_set_type,
	make_sterilize_program,
	make_sterilizer,
	make_wash_machine,
	make_wash_program,
	make_wash_ready_set,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

WASH_STATION = "TR-002"
LOAD_STATION = "TR-005"


def set_type(method="Steam"):
	return make_set_type("SP" + frappe.generate_hash(length=4).upper(), method=method)


def link(set_type_doc, *rows):
	doc = frappe.get_doc("Instrument Set Type", set_type_doc.name)
	doc.set("programs", [{"program": program.name, "is_default": int(default)} for program, default in rows])
	doc.save()
	return doc


def set_control(level):
	frappe.db.set_single_value("TraceCore Settings", "program_control", level)


def blocked(case, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


class WashCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		set_control("Warn")
		self.washer = make_wash_machine()
		self.general = make_wash_program(self.washer.name, program_name="A Rửa thường")
		self.mis = make_wash_program(self.washer.name, program_name="B Rửa MIS")
		self.scope = link(set_type(), (self.mis, True))
		self.ortho = link(set_type(), (self.general, True), (self.mis, False))
		self.employee = make_employee()

	def wash(self, program, units, reason=None):
		return washing.start(
			self.washer.name,
			program.name,
			[unit.name for unit in units],
			[],
			WASH_STATION,
			client_time.utc_now(),
			self.employee.name,
			override_reason=reason,
		)


class TestWashScan(WashCase):
	def test_scan_reports_machine_default_and_set_programs(self):
		frappe.db.set_value("Equipment", self.washer.name, "default_program", self.mis.name)
		scan = washing.scan_machine(self.washer.name)
		self.assertEqual(scan["equipment"].default_program, self.mis.name)
		self.assertEqual(scan["set_programs"][self.scope.name]["default"], self.mis.name)
		self.assertEqual(scan["program_control"], "Warn")

	@bru("BRU-REP-017")
	def test_admitted_set_carries_fit_and_default(self):
		unit = make_wash_ready_set(set_type=self.scope.name)
		admitted = washing.admit_set(unit.name, self.washer.name, program=self.general.name)
		self.assertEqual(admitted["program_fit"], "Outside")
		self.assertEqual(admitted["program_default"], self.mis.name)
		plain = make_wash_ready_set(set_type=set_type().name)
		self.assertEqual(
			washing.admit_set(plain.name, self.washer.name, program=self.general.name)["program_fit"],
			"Unmapped",
		)

	@bru("BRU-REP-017")
	def test_block_level_refuses_set_outside_the_list(self):
		set_control("Block")
		unit = make_wash_ready_set(set_type=self.scope.name)
		block = blocked(self, washing.admit_set, unit.name, self.washer.name, program=self.general.name)
		self.assertEqual(block.code, "PROGRAM_NOT_FOR_SET")
		self.assertIn(block.code, frappe.db.get_value("TraceCore Error Code", "TB-005", "block_codes"))

	def test_old_kiosk_without_program_and_repeat_scan_are_not_blocked(self):
		set_control("Block")
		unit = make_wash_ready_set(set_type=self.scope.name)
		admitted = washing.admit_set(unit.name, self.washer.name)
		self.assertEqual((admitted["program_fit"], admitted["program_default"]), (None, self.mis.name))
		repeat = washing.admit_set(unit.name, self.washer.name, [unit.name], program=self.general.name)
		self.assertTrue(repeat["duplicate"])
		self.assertEqual(repeat["program_fit"], "Outside")


class TestWashStart(WashCase):
	@bru("BRU-REP-017")
	def test_warn_level_records_suggestion_and_override(self):
		unit = make_wash_ready_set(set_type=self.scope.name)
		batch = frappe.get_doc("Wash Batch", self.wash(self.general, [unit])["batch"])
		self.assertEqual(batch.suggested_program, self.mis.name)
		self.assertEqual(batch.program, self.general.name)
		self.assertEqual(batch.program_override_by, self.employee.name)
		self.assertIsNone(batch.program_override_reason)

	def test_listed_program_has_no_override(self):
		unit = make_wash_ready_set(set_type=self.ortho.name)
		batch = frappe.get_doc("Wash Batch", self.wash(self.mis, [unit])["batch"])
		self.assertEqual(batch.suggested_program, self.general.name)
		self.assertIsNone(batch.program_override_by)

	@bru("BRU-REP-017")
	def test_override_level_needs_reason(self):
		set_control("Override")
		unit = make_wash_ready_set(set_type=self.scope.name)
		block = blocked(self, self.wash, self.general, [unit])
		self.assertEqual(block.code, "PROGRAM_OVERRIDE_REASON_REQUIRED")
		self.assertFalse(frappe.db.exists("Wash Batch Set Unit", {"set_unit": unit.name}))
		batch = frappe.get_doc("Wash Batch", self.wash(self.general, [unit], reason="Máy MIS hỏng")["batch"])
		self.assertEqual(batch.program_override_reason, "Máy MIS hỏng")

	@bru("BRU-REP-017")
	def test_block_level_leaves_outside_sets_out_of_the_batch(self):
		set_control("Block")
		outside = make_wash_ready_set(set_type=self.scope.name)
		listed = make_wash_ready_set(set_type=self.ortho.name)
		result = self.wash(self.general, [outside, listed])
		self.assertEqual(result["sets"], [listed.name])
		self.assertEqual([row["code"] for row in result["rejected"]], ["PROGRAM_NOT_FOR_SET"])


class LoadCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		set_control("Warn")
		self.machine = make_sterilizer()
		self.p134 = make_sterilize_program(self.machine.name, program_name="A Hấp 134")
		self.p121 = make_sterilize_program(self.machine.name, program_name="B Hấp 121")
		self.rubber = link(set_type(), (self.p121, True))
		self.employee = make_employee()

	def pack(self):
		return make_load_ready_pack(set_type=self.rubber.name)


class TestLoad(LoadCase):
	def test_scan_reports_set_programs(self):
		scan = sterilizing.scan_machine(self.machine.name)
		self.assertEqual(
			scan["set_programs"][self.rubber.name], {"default": self.p121.name, "allowed": [self.p121.name]}
		)

	@bru("BRU-REP-017")
	def test_admitted_pack_carries_fit(self):
		admitted = sterilizing.admit_pack(self.pack().name, self.machine.name, self.p134.name)
		self.assertEqual((admitted["program_fit"], admitted["program_default"]), ("Outside", self.p121.name))

	@bru("BRU-REP-017")
	def test_block_level_refuses_pack_and_recheck_marks_it(self):
		pack = self.pack()
		set_control("Block")
		block = blocked(self, sterilizing.admit_pack, pack.name, self.machine.name, self.p134.name)
		self.assertEqual(block.code, "PROGRAM_NOT_FOR_SET")
		rows = sterilizing.recheck_packs(self.machine.name, self.p134.name, [pack.name])
		self.assertEqual((rows[0]["ok"], rows[0]["code"]), (False, "PROGRAM_NOT_FOR_SET"))
		self.assertTrue(sterilizing.recheck_packs(self.machine.name, self.p121.name, [pack.name])[0]["ok"])

	@bru("BRU-REP-017")
	def test_complete_records_override_with_reason(self):
		set_control("Override")
		pack = self.pack()
		args = (
			self.machine.name,
			self.p134.name,
			[pack.name],
			LOAD_STATION,
			client_time.utc_now(),
			self.employee.name,
		)
		block = blocked(self, sterilizing.complete, *args)
		self.assertEqual(block.code, "PROGRAM_OVERRIDE_REASON_REQUIRED")
		self.assertEqual(frappe.db.get_value("Pack", pack.name, "status"), "Packed")
		load = frappe.get_doc(
			"Sterilization Load", sterilizing.complete(*args, override_reason="Hết chu trình 121")["load"]
		)
		self.assertEqual(
			(load.suggested_program, load.program_override_by, load.program_override_reason),
			(self.p121.name, self.employee.name, "Hết chu trình 121"),
		)

	def test_method_check_still_blocks_at_warn_level(self):
		plasma_type = link(set_type("Plasma"))
		pack = make_load_ready_pack(method="Plasma", set_type=plasma_type.name)
		block = blocked(self, sterilizing.admit_pack, pack.name, self.machine.name, self.p134.name)
		self.assertEqual(block.code, "PACK_INCOMPATIBLE")
