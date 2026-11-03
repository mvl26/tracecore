"""Patch điền Loại thiết bị cho chương trình cũ (A-110): ô chọn chương trình ở tab Chương trình theo máy lọc theo trường này."""

import frappe

from tracecore.patches.v0_1 import fill_program_equipment_type
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase


class TestFillProgramEquipmentType(IsolatedTestCase):
	def test_old_programs_get_the_type_of_their_machine(self):
		washer = factories.make_wash_machine()
		sterilizer = factories.make_sterilizer()
		old_wash = factories.make_wash_program(washer.name).name
		old_steam = factories.make_sterilize_program(sterilizer.name).name
		for program in (old_wash, old_steam):
			frappe.db.set_value("Process Program", program, "equipment_type", None, update_modified=False)
		fill_program_equipment_type.execute()
		self.assertEqual(
			frappe.db.get_value("Process Program", old_wash, "equipment_type"), "Washer-Disinfector"
		)
		self.assertEqual(
			frappe.db.get_value("Process Program", old_steam, "equipment_type"), "Steam Sterilizer"
		)

	def test_program_whose_machine_type_changed_is_corrected(self):
		sterilizer = factories.make_sterilizer()
		program = factories.make_sterilize_program(sterilizer.name).name
		frappe.db.set_value(
			"Process Program", program, "equipment_type", "Washer-Disinfector", update_modified=False
		)
		fill_program_equipment_type.execute()
		self.assertEqual(
			frappe.db.get_value("Process Program", program, "equipment_type"), "Steam Sterilizer"
		)
