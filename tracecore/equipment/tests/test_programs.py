import frappe

from tracecore.equipment import programs
from tracecore.equipment.status import set_status
from tracecore.tests.factories import make_equipment, make_item, make_program
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Asset", "Item", "User"]


class TestPrograms(IsolatedTestCase):
	@bru("BRU-EQP-003")
	def test_active_programs_only_of_selected_equipment(self):
		first = make_equipment(name="Máy A", serial="SN-PA")
		second = make_equipment(name="Máy B", serial="SN-PB")
		make_program(first.name, code="PA-2", program_name="B chương trình")
		make_program(first.name, code="PA-1", program_name="A chương trình", temperature=134, pressure=2.1)
		stopped = make_program(first.name, code="PA-3", program_name="C ngừng dùng")
		stopped.is_active = 0
		stopped.save()
		make_program(second.name, code="PB-1")

		result = programs.active_programs(first.name)
		self.assertEqual([row["program_code"] for row in result], ["PA-1", "PA-2"])
		self.assertEqual(
			set(result[0]),
			{
				"program_code",
				"program_name",
				"temperature",
				"pressure",
				"duration_min",
				"requires_bi",
				"norm_status",
				"compatible_pack_types",
			},
		)
		self.assertEqual(result[0]["temperature"], 134)
		self.assertEqual(result[0]["compatible_pack_types"], [])
		self.assertEqual([r["program_code"] for r in programs.active_programs(second.name)], ["PB-1"])

	def test_active_programs_lists_pack_types(self):
		equipment = make_equipment(name="Máy C", serial="SN-PC")
		pack = make_item("PRG-PACK-1", "Packaging")
		make_program(equipment.name, code="PC-1", compatible_pack_types=[{"pack_type": pack.name}])
		self.assertEqual(programs.active_programs(equipment.name)[0]["compatible_pack_types"], [pack.name])

	@bru("BRU-EQP-003")
	def test_copy_program_same_model_only(self):
		source_eq = make_equipment(name="Máy nguồn", serial="SN-S")
		same = make_equipment(
			name="Máy cùng model", serial="SN-T", manufacturer=" test maker ", model="tm-1 "
		)
		other = make_equipment(name="Máy khác model", serial="SN-O", model="TM-2")
		item = make_item("CP-CI-1", "Chemical Indicator")
		pack = make_item("CP-PACK-1", "Packaging")
		source = make_program(
			source_eq.name,
			code="SRC-1",
			water=20,
			temperature=134,
			pressure=2.1,
			requires_bi=1,
			consumables=[{"item": item.name, "qty_per_load": 1}],
			compatible_pack_types=[{"pack_type": pack.name}],
			parameters=[{"parameter_name": "Nhiệt", "unit": "°C", "min_value": 130, "max_value": 140}],
		)

		with self.assertRaises(frappe.ValidationError):
			programs.copy_program(source.name, other.name, "CPY-X")
		with self.assertRaises(frappe.ValidationError):
			programs.copy_program(source.name, source_eq.name, "CPY-SELF")

		name = programs.copy_program(source.name, same.name, "cpy-1")
		copy = frappe.get_doc("Process Program", name)
		self.assertEqual(name, "CPY-1")
		self.assertEqual(copy.equipment, same.name)
		self.assertEqual(copy.is_active, 1)
		self.assertEqual((copy.temperature, copy.pressure, copy.requires_bi), (134, 2.1, 1))
		self.assertEqual(copy.duration_min, source.duration_min)
		self.assertEqual(copy.norm_status, "Complete")
		self.assertEqual([r.item for r in copy.consumables], [item.name])
		self.assertEqual([r.pack_type for r in copy.compatible_pack_types], [pack.name])
		self.assertEqual([(r.parameter_name, r.max_value) for r in copy.parameters], [("Nhiệt", 140)])

		with self.assertRaises(frappe.DuplicateEntryError):
			programs.copy_program(source.name, same.name, "CPY-1")

	def test_copy_program_rejects_retired_target(self):
		source_eq = make_equipment(name="Máy nguồn 2", serial="SN-S2")
		target = make_equipment(name="Máy đích", serial="SN-T2")
		source = make_program(source_eq.name, code="SRC-2")
		set_status(target.name, "Retired", "Hỏng")
		with self.assertRaises(frappe.ValidationError):
			programs.copy_program(source.name, target.name, "CPY-R")

	def test_copy_program_defaults_are_permission_checked_and_drop_default_flag(self):
		from tracecore.equipment.tests.test_norms import make_type_norm
		from tracecore.tests.factories import make_user

		make_type_norm()
		source_eq = make_equipment(name="Máy nguồn 3", serial="SN-S3")
		target = make_equipment(name="Máy đích 3", serial="SN-T3")
		source = make_program(source_eq.name, code="SRC-3", use_default_norms=1)
		frappe.set_user(make_user("prog-r04@example.com", ["TC R04"]))
		try:
			with self.assertRaises(frappe.PermissionError):
				programs.copy_program(source.name, target.name, "CPY-NP")
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("Process Program", "CPY-NP"))
		name = programs.copy_program(source.name, target.name, "CPY-DF")
		self.assertEqual(frappe.db.get_value("Process Program", name, "use_default_norms"), 0)
		name = programs.copy_program(source.name, target.name, "CPY-KEEP", keep_default_norms=True)
		self.assertEqual(frappe.db.get_value("Process Program", name, "use_default_norms"), 1)
