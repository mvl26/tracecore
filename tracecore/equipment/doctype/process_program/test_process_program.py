import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

from tracecore.equipment.status import set_status
from tracecore.tests.factories import make_equipment, make_item, make_program
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Asset", "Item", "User"]


class TestProcessProgram(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.equipment = make_equipment()

	def test_program_code_normalized_and_unique(self):
		doc = make_program(self.equipment.name, code="mh-01-134")
		self.assertEqual(doc.name, "MH-01-134")
		self.assertEqual(doc.program_code, "MH-01-134")
		with self.assertRaises(frappe.ValidationError):
			make_program(self.equipment.name, code="MH 01")
		with self.assertRaises(frappe.DuplicateEntryError):
			make_program(self.equipment.name, code="MH-01-134")

	def test_program_requires_equipment_and_equipment_cannot_change(self):
		with self.assertRaises(frappe.ValidationError):
			make_program(None, code="NOEQ-1")
		doc = make_program(self.equipment.name)
		other = make_equipment(name="Máy khác", serial="SN-OTHER")
		doc.reload()
		doc.equipment = other.name
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_consumable_needs_a_positive_quantity(self):
		item = make_item("PP-CI-1", "Chemical Indicator")
		with self.assertRaises(frappe.ValidationError):
			make_program(self.equipment.name, code="C-1", consumables=[{"item": item.name}])
		with self.assertRaises(frappe.ValidationError):
			make_program(
				self.equipment.name, code="C-2", consumables=[{"item": item.name, "qty_per_load": -1}]
			)
		with self.assertRaises(frappe.ValidationError):
			make_program(
				self.equipment.name,
				code="C-3",
				consumables=[
					{"item": item.name, "qty_per_load": 1},
					{"item": item.name, "qty_per_pack": 2},
				],
			)
		doc = make_program(
			self.equipment.name, code="C-4", consumables=[{"item": item.name, "qty_per_pack": 2}]
		)
		self.assertEqual(len(doc.consumables), 1)

	def test_parameter_min_not_above_max(self):
		def params(*rows):
			return [{"parameter_name": n, "min_value": lo, "max_value": hi} for n, lo, hi in rows]

		with self.assertRaises(frappe.ValidationError):
			make_program(self.equipment.name, code="P-1", parameters=params(("Nhiệt", 140, 130)))
		with self.assertRaises(frappe.ValidationError):
			make_program(self.equipment.name, code="P-2", parameters=params(("Nhiệt", 1, 2), ("nhiệt", 1, 2)))
		with self.assertRaises(frappe.ValidationError):
			make_program(self.equipment.name, code="P-3", parameters=[{"parameter_name": " "}])
		doc = make_program(self.equipment.name, code="P-4", parameters=params(("Nhiệt", 0, 0), ("Áp", 1, 2)))
		self.assertEqual(len(doc.parameters), 2)

	def test_parameter_range_may_be_one_sided(self):
		# Float chưa nhập đọc là 0: chỉ kiểm min <= max khi cả hai > 0
		doc = make_program(
			self.equipment.name,
			code="P-5",
			parameters=[
				{"parameter_name": "Chỉ tối thiểu", "min_value": 121},
				{"parameter_name": "Chỉ tối đa", "max_value": 3},
				{"parameter_name": "Không dải"},
			],
		)
		doc.reload()
		self.assertEqual([(r.min_value, r.max_value) for r in doc.parameters], [(121, 0), (0, 3), (0, 0)])
		with self.assertRaisesRegex(frappe.ValidationError, "Minimum cannot be above Maximum"):
			make_program(
				self.equipment.name,
				code="P-6",
				parameters=[{"parameter_name": "Cả hai", "min_value": 5, "max_value": 4}],
			)

	def test_duplicate_pack_type_rejected(self):
		pack = make_item("PP-PACK-1", "Packaging")
		with self.assertRaises(frappe.ValidationError):
			make_program(
				self.equipment.name,
				code="K-1",
				compatible_pack_types=[{"pack_type": pack.name}, {"pack_type": pack.name}],
			)
		doc = make_program(self.equipment.name, code="K-2", compatible_pack_types=[{"pack_type": pack.name}])
		self.assertEqual(len(doc.compatible_pack_types), 1)

	def test_negative_norms_rejected(self):
		for field in ("duration_min", "kwh_per_cycle", "water_l_per_cycle", "steam_kg_per_cycle"):
			with self.assertRaises(frappe.ValidationError, msg=field):
				make_program(self.equipment.name, code="N-1", **{field: -1})

	@bru("BRU-EQP-003")
	def test_program_data_kept_when_inactive(self):
		item = make_item("PP-CI-2", "Chemical Indicator")
		doc = make_program(
			self.equipment.name,
			code="KEEP-1",
			consumables=[{"item": item.name, "qty_per_load": 1}],
			parameters=[{"parameter_name": "Nhiệt", "unit": "°C", "min_value": 130, "max_value": 140}],
		)
		doc.reload()
		doc.is_active = 0
		doc.save()
		doc.reload()
		self.assertEqual(doc.is_active, 0)
		self.assertEqual(doc.duration_min, 4)
		self.assertEqual(len(doc.consumables), 1)
		self.assertEqual(len(doc.parameters), 1)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Process Program", doc.name, force=True)
		self.assertTrue(frappe.db.exists("Process Program", doc.name))

	def test_retired_equipment_cannot_get_new_program(self):
		doc = make_program(self.equipment.name, code="OLD-1")
		set_status(self.equipment.name, "Retired", "Hết đời")
		with self.assertRaises(frappe.ValidationError):
			make_program(self.equipment.name, code="NEW-1")
		doc.reload()
		doc.is_active = 0  # chương trình có sẵn vẫn sửa/ngừng được
		doc.save()

	def test_permissions_match_q7(self):
		validate_permissions_for_doctype("Process Program")
		perms = {row.role: row for row in frappe.get_meta("Process Program").permissions}
		for role in ("System Manager", "TC R10"):
			for right in ("read", "write", "create", "report"):
				self.assertEqual(perms[role].get(right), 1, msg=(role, right))
		for role in ("TC R01", "TC R02", "TC R03", "TC R04", "TC R05", "TC R06", "TC R09"):
			self.assertEqual(perms[role].read, 1, msg=role)
			self.assertFalse(perms[role].write or perms[role].create, msg=role)
		self.assertFalse(any(row.delete for row in perms.values()))

	def test_r02_cannot_write_process_program(self):
		doc = make_program(self.equipment.name, code="R02-1")
		user = "r02.program@test.local"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{"doctype": "User", "email": user, "first_name": "R02", "roles": [{"role": "TC R02"}]}
			).insert(ignore_permissions=True)
		self.assertTrue(frappe.has_permission("Process Program", "read", doc=doc, user=user))
		self.assertFalse(frappe.has_permission("Process Program", "write", doc=doc, user=user))
		self.assertFalse(frappe.has_permission("Process Program", "create", user=user))

	def test_norm_flags_are_read_only_defaults(self):
		meta = frappe.get_meta("Process Program")
		self.assertEqual(meta.get_field("norm_status").read_only, 1)
		self.assertEqual(meta.get_field("outside_safe_range").read_only, 1)
		self.assertEqual(make_program(self.equipment.name, code="DF-1").norm_status, "Missing")
