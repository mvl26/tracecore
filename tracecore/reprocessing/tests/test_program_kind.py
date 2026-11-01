"""Chương trình test và loại gói tương thích ở T5 (A-83; ticket #1821, #1839, #1840; FR-M2-09, FR-M5-02)."""

import frappe

from tracecore.core import client_time
from tracecore.core.errors import BlockedError
from tracecore.patches.v0_1 import classify_test_programs
from tracecore.reprocessing import load_repair, sterilizing
from tracecore.tests.factories import (
	make_employee,
	make_load,
	make_load_ready_pack,
	make_program,
	make_sterilize_program,
	make_sterilizer,
)
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def code(prefix="BD"):
	return prefix + "-" + frappe.generate_hash(length=6).upper()


def blocked(case, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


class ProgramKindCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_sterilizer()
		self.regular = make_sterilize_program(self.machine.name, program_name="Z 134 C", code=code("MH"))
		self.bowie = make_program(
			self.machine.name, code=code(), program_name="A Test Bowie-Dick", program_kind="Test"
		)


class TestLoadingList(ProgramKindCase):
	def test_scan_lists_no_test_program(self):
		names = [row["program_code"] for row in sterilizing.scan_machine(self.machine.name)["programs"]]
		self.assertEqual(names, [self.regular.name])

	def test_default_program_is_reported_only_when_it_can_be_chosen(self):
		other = make_sterilize_program(self.machine.name, program_name="B 121 C", code=code("MH"))
		self.assertIsNone(sterilizing.scan_machine(self.machine.name)["equipment"].default_program)
		machine = frappe.get_doc("Equipment", self.machine.name)
		machine.default_program = self.regular.name
		machine.save()
		scan = sterilizing.scan_machine(self.machine.name)
		self.assertEqual(scan["equipment"].default_program, self.regular.name)
		self.assertEqual(scan["programs"][0]["program_code"], other.name)  # danh sách vẫn theo tên
		frappe.db.set_value("Process Program", self.regular.name, "is_active", 0)
		self.assertIsNone(sterilizing.scan_machine(self.machine.name)["equipment"].default_program)

	def test_default_program_must_be_a_regular_active_program_of_the_machine(self):
		machine = frappe.get_doc("Equipment", self.machine.name)
		foreign = make_sterilize_program(make_sterilizer().name, code=code("MH"))
		for bad in (self.bowie.name, foreign.name):
			machine.default_program = bad
			self.assertRaises(frappe.ValidationError, machine.save)
		machine.reload()
		machine.default_program = self.regular.name
		machine.save()


class TestAdmission(ProgramKindCase):
	def test_pack_is_refused_on_a_test_program(self):
		pack = make_load_ready_pack()
		block = blocked(self, sterilizing.admit_pack, pack.name, self.machine.name, self.bowie.name)
		self.assertEqual(block.code, "PROGRAM_TEST_ONLY")
		self.assertEqual(block.http_status, 422)
		self.assertIn(block.code, frappe.db.get_value("TraceCore Error Code", "DC-006", "block_codes"))

	def test_complete_refuses_a_test_program_and_leaves_the_pack(self):
		pack = make_load_ready_pack()
		block = blocked(
			self,
			sterilizing.complete,
			self.machine.name,
			self.bowie.name,
			[pack.name],
			"TR-005",
			client_time.utc_now(),
			"HR-EMP-TEST",
		)
		self.assertEqual(block.code, "PROGRAM_TEST_ONLY")
		self.assertEqual(frappe.db.get_value("Pack", pack.name, "status"), "Packed")

	def test_empty_compatible_list_takes_no_pack(self):
		frappe.db.delete("Program Compatible Pack Type", {"parent": self.regular.name})
		pack = make_load_ready_pack()
		block = blocked(self, sterilizing.admit_pack, pack.name, self.machine.name, self.regular.name)
		self.assertEqual(block.code, "PACK_INCOMPATIBLE")
		self.assertIn(self.regular.name, block.reason)

	def test_listed_pack_type_is_accepted(self):
		admitted = sterilizing.admit_pack(make_load_ready_pack().name, self.machine.name, self.regular.name)
		self.assertFalse(admitted["duplicate"])

	def test_load_document_refuses_a_test_program_on_every_save(self):
		self.assertRaises(
			frappe.ValidationError, make_load, self.machine, self.bowie, [make_load_ready_pack()]
		)
		load = make_load(self.machine, self.regular, [make_load_ready_pack()])
		frappe.db.set_value("Sterilization Load", load.name, "program", self.bowie.name)
		doc = frappe.get_doc("Sterilization Load", load.name)
		doc.flags.tc_sterilizing = True
		self.assertRaises(frappe.ValidationError, doc.save)


class TestRepairAndPatch(ProgramKindCase):
	def stale_load(self):
		"""Mẻ cũ: chương trình lúc nạp là thường, nay đã phân loại test; gói đang Trong mẻ."""
		pack = make_load_ready_pack()
		load = make_load(self.machine, self.regular, [pack], operator=make_employee().name)
		frappe.db.set_value("Sterilization Load", load.name, "program", self.bowie.name)
		return load, pack

	def test_listing_and_dry_run_change_nothing(self):
		load, pack = self.stale_load()
		self.assertIn(load.name, [row["load"] for row in load_repair.test_loads_with_packs()])
		result = load_repair.detach_packs(load.name)
		self.assertEqual((result["packs"], result["applied"]), ([pack.name], False))
		self.assertEqual(frappe.db.get_value("Pack", pack.name, "status"), "In Load")

	def test_detach_returns_packs_to_loading_and_closes_the_load(self):
		load, pack = self.stale_load()
		self.assertTrue(load_repair.detach_packs(load.name, dry_run=0)["applied"])
		self.assertEqual(frappe.db.get_value("Pack", pack.name, ["status", "load"]), ("Packed", None))
		self.assertEqual(frappe.db.get_value("Sterilization Load", load.name, "status"), "Failed")
		self.assertEqual(frappe.db.count("Load Pack", {"parent": load.name}), 0)
		self.assertIsNotNone(
			load_repair.detach_packs(load.name, dry_run=0)["refused"]
		)  # chạy lại không đổi gì
		self.assertTrue(sterilizing.admit_pack(pack.name, self.machine.name, self.regular.name))

	def test_regular_program_load_is_refused(self):
		load = make_load(self.machine, self.regular, [make_load_ready_pack()])
		self.assertEqual(load_repair.detach_packs(load.name, dry_run=0)["refused"], "not_a_test_program")

	def test_patch_marks_only_obvious_test_names_on_sterilizers(self):
		leak = make_sterilize_program(self.machine.name, program_name="Test rò rỉ khí", code=code("MH"))
		vacuum = make_sterilize_program(self.machine.name, program_name="Vacuum test", code=code("MH"))
		other = make_sterilize_program(self.machine.name, program_name="134°C - 5 phút", code=code("MH"))
		classify_test_programs.execute()
		kind = lambda doc: frappe.db.get_value("Process Program", doc.name, "program_kind")  # noqa: E731
		self.assertEqual((kind(leak), kind(vacuum), kind(other)), ("Test", "Test", "Regular"))
		log = frappe.get_all(
			"Error Log",
			filters={"method": "A-83 classify_test_programs"},
			fields=["error"],
			limit=1,
			order_by="creation desc",
		)
		self.assertIn(other.name, log[0].error)
