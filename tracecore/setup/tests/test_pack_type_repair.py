"""Công cụ sửa danh sách loại gói của chương trình máy tiệt khuẩn (#1839 T5-06, #1843 T4-03, A-83, A-97)."""

from unittest.mock import patch

import frappe

from tracecore.core.errors import BlockedError
from tracecore.equipment.doctype.process_program.process_program import ProcessProgram
from tracecore.reprocessing import sterilizing
from tracecore.setup import pack_type_repair
from tracecore.tests.factories import (
	make_item,
	make_load_ready_pack,
	make_program,
	make_sterilize_program,
	make_sterilizer,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def code(prefix):
	return f"{prefix}-{frappe.generate_hash(length=8).upper()}"


def packaging(prefix="PK", method=None):
	return make_item(code(prefix), "Packaging", method=method, shelf_life_days=30).name


def rows(program):
	return set(
		frappe.get_all(
			"Program Compatible Pack Type",
			filters={"parent": program.name, "parenttype": "Process Program"},
			pluck="pack_type",
		)
	)


def group_of(item):
	return frappe.db.get_value("Item", item, "tc_item_group_cssd")


def audit_rows():
	return frappe.db.count("Audit Log", {"reason": pack_type_repair.EVENT})


class TestPackTypeRepair(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.steam_code = packaging(method="Steam")
		self.plasma_code = packaging(method="Plasma")
		self.legacy = packaging("LEGACY", method="Steam")
		self.steam_machine = make_sterilizer()
		self.plasma_machine = make_sterilizer("Plasma Sterilizer")
		self.steam_program = make_sterilize_program(self.steam_machine.name, pack_types=[self.legacy])
		self.plasma_program = make_sterilize_program(self.plasma_machine.name, pack_types=[self.legacy])
		self.test_program = make_program(self.steam_machine.name, code=code("BD"), program_kind="Test")
		# mã vật tư cũ trong bảng tương thích: lưu được lúc còn nhóm Packaging, sau đó không còn là loại gói
		frappe.db.set_value("Item", self.legacy, "tc_item_group_cssd", "Other")

	def blocked_code(self, pack, machine, program):
		with self.assertRaises(BlockedError) as caught:
			sterilizing.admit_pack(pack.name, machine.name, program.name, [])
		return caught.exception.block

	def test_requires_administrator(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				pack_type_repair.run()
		finally:
			frappe.set_user("Administrator")

	def test_is_not_whitelisted(self):
		self.assertNotIn(pack_type_repair.run, frappe.whitelisted)

	def test_default_is_a_dry_run_that_writes_nothing(self):
		accessory = packaging("ACC", method="Steam")
		modified = frappe.db.get_value("Process Program", self.steam_program.name, "modified")
		before = audit_rows()
		result = pack_type_repair.run(accessories=[accessory])
		self.assertTrue(result["dry_run"])
		self.assertFalse(result["applied"])
		self.assertEqual(rows(self.steam_program), {self.legacy})
		self.assertEqual(rows(self.plasma_program), {self.legacy})
		self.assertEqual(group_of(accessory), "Packaging")
		self.assertEqual(
			frappe.db.get_value("Process Program", self.steam_program.name, "modified"), modified
		)
		self.assertEqual(audit_rows(), before)
		# báo trước đúng điều sẽ làm
		steam = result["methods"]["Steam"]
		self.assertIn(self.steam_code, steam["codes_added"])
		self.assertIn(self.legacy, steam["codes_removed"])
		self.assertNotIn(accessory, steam["codes_added"])
		self.assertEqual(result["accessories_moved"], [accessory])

	@bru("BRU-REP-004")
	def test_apply_lets_steam_pack_into_steam_program_only(self):
		pack = make_load_ready_pack(pack_type=self.steam_code)
		plasma_pack = make_load_ready_pack(method="Plasma", pack_type=self.steam_code)
		self.assertEqual(
			self.blocked_code(pack, self.steam_machine, self.steam_program).code, "PACK_INCOMPATIBLE"
		)

		result = pack_type_repair.run(dry_run=0)

		self.assertTrue(result["applied"])
		self.assertFalse(result["dry_run"])
		self.assertIn(self.steam_code, rows(self.steam_program))
		self.assertNotIn(self.plasma_code, rows(self.steam_program))
		self.assertNotIn(self.legacy, rows(self.steam_program))
		self.assertEqual(
			sterilizing.admit_pack(pack.name, self.steam_machine.name, self.steam_program.name, [])[
				"pack_type"
			],
			self.steam_code,
		)
		# gói hơi nước vào máy plasma: sai phương pháp; loại gói hơi nước ở chương trình plasma: không có trong danh sách
		self.assertEqual(
			self.blocked_code(pack, self.plasma_machine, self.plasma_program).code, "PACK_INCOMPATIBLE"
		)
		block = self.blocked_code(plasma_pack, self.plasma_machine, self.plasma_program)
		self.assertEqual(block.code, "PACK_INCOMPATIBLE")
		self.assertIn(self.plasma_code, rows(self.plasma_program))
		self.assertNotIn(self.steam_code, rows(self.plasma_program))
		self.assertEqual(frappe.db.get_value("Pack", pack.name, "status"), sterilizing.LOADABLE)

	def test_disabled_item_is_not_listed(self):
		disabled = packaging(method="Steam")
		frappe.db.set_value("Item", disabled, "disabled", 1)
		pack_type_repair.run(dry_run=0)
		self.assertNotIn(disabled, rows(self.steam_program))

	def test_test_program_stays_empty(self):
		pack_type_repair.run(dry_run=0)
		self.assertEqual(rows(self.test_program), set())

	def test_inactive_program_is_untouched(self):
		frappe.db.set_value("Process Program", self.steam_program.name, "is_active", 0)
		pack_type_repair.run(dry_run=0)
		self.assertEqual(rows(self.steam_program), {self.legacy})

	def test_second_apply_changes_nothing(self):
		accessory = packaging("ACC", method="Steam")
		pack_type_repair.run(dry_run=0, accessories=[accessory])
		after_first = rows(self.steam_program)
		modified = frappe.db.get_value("Process Program", self.steam_program.name, "modified")
		logs = audit_rows()

		second = pack_type_repair.run(dry_run=0, accessories=[accessory])

		self.assertEqual(rows(self.steam_program), after_first)
		self.assertEqual(
			frappe.db.get_value("Process Program", self.steam_program.name, "modified"), modified
		)
		self.assertEqual(audit_rows(), logs)
		self.assertEqual(second["accessories_moved"], [])
		self.assertEqual(second["accessories_already_moved"], [accessory])
		for summary in second["methods"].values():
			self.assertEqual(summary["programs_changed"], 0)
			self.assertEqual(summary["codes_added"], [])
			self.assertEqual(summary["codes_removed"], [])

	def test_apply_writes_audit_log(self):
		accessory = packaging("ACC", method="Steam")
		pack_type_repair.run(dry_run=0, accessories=[accessory])
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{
					"reason": pack_type_repair.EVENT,
					"ref_doctype": "Process Program",
					"ref_name": self.steam_program.name,
				},
			)
		)
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"reason": pack_type_repair.EVENT, "ref_doctype": "Item", "ref_name": accessory}
			)
		)

	def test_accessory_moves_and_leaves_the_lists(self):
		accessory = packaging("ACC", method="Steam")
		pack_type_repair.run(dry_run=0)
		self.assertIn(accessory, rows(self.steam_program))

		result = pack_type_repair.run(dry_run=0, accessories=f"{accessory}, ")

		self.assertEqual(group_of(accessory), "Packaging Accessory")
		self.assertNotIn(accessory, rows(self.steam_program))
		self.assertEqual(result["accessories_moved"], [accessory])
		self.assertIn(accessory, result["methods"]["Steam"]["codes_removed"])
		self.assertTrue(frappe.db.exists("Item", accessory))

	def test_unusable_accessory_is_refused_before_any_write(self):
		other = make_item(code("OTH"), "Other").name
		missing = code("NOPE")
		preview = pack_type_repair.run(accessories=[other, missing])
		self.assertEqual(
			{row["item"]: row["reason"] for row in preview["accessories_refused"]},
			{other: "not_packaging", missing: "not_found"},
		)
		with self.assertRaises(frappe.ValidationError):
			pack_type_repair.run(dry_run=0, accessories=[missing])
		self.assertEqual(rows(self.steam_program), {self.legacy})

	def test_blank_method_item_is_listed_and_not_added(self):
		blank = packaging("BLANK")
		result = pack_type_repair.run(dry_run=0)
		self.assertIn(blank, result["blank_method_items"])
		self.assertNotIn(blank, rows(self.steam_program))
		self.assertNotIn(blank, rows(self.plasma_program))

	def test_open_packs_that_would_not_fit_are_listed_and_left_alone(self):
		bad = make_load_ready_pack(pack_type=self.legacy)
		good = make_load_ready_pack(pack_type=self.steam_code)
		result = pack_type_repair.run(dry_run=0)
		listed = {row["pack"]: row for row in result["methods"]["Steam"]["open_packs_incompatible"]}
		self.assertEqual(listed[bad.name]["pack_type"], self.legacy)
		self.assertEqual(listed[bad.name]["status"], sterilizing.LOADABLE)
		self.assertNotIn(good.name, listed)
		self.assertEqual(frappe.db.get_value("Pack", bad.name, "pack_type"), self.legacy)
		self.assertEqual(frappe.db.get_value("Pack", bad.name, "status"), sterilizing.LOADABLE)

	def test_failure_rolls_everything_back(self):
		accessory = packaging("ACC", method="Steam")
		logs = audit_rows()
		# chương trình đầu lưu xong, chương trình sau hỏng: mọi thay đổi phải mất hết
		with patch.object(
			ProcessProgram, "_validate_parameters", side_effect=[None, frappe.ValidationError("hỏng")]
		):
			with self.assertRaises(frappe.ValidationError):
				pack_type_repair.run(dry_run=0, accessories=[accessory])
		self.assertEqual(group_of(accessory), "Packaging")
		self.assertEqual(rows(self.steam_program), {self.legacy})
		self.assertEqual(rows(self.plasma_program), {self.legacy})
		self.assertEqual(audit_rows(), logs)
