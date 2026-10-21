import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

from tracecore.equipment.status import set_status
from tracecore.tests.factories import make_equipment
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Asset", "Item", "User"]


class TestEquipment(IsolatedTestCase):
	@bru("BRU-ID-006")
	def test_code_tb_registered_and_immutable(self):
		doc = make_equipment()
		self.assertRegex(doc.name, r"^TB-\d{4}$")
		row = frappe.db.get_value(
			"Code Registry", doc.name, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
		)
		self.assertEqual(
			(row.prefix, row.ref_doctype, row.ref_name, row.status),
			("TB", "Equipment", doc.name, "Active"),
		)
		with self.assertRaises(frappe.ValidationError):
			frappe.rename_doc("Equipment", doc.name, "TB-9999")
		doc.reload()
		doc.equipment_name = "Đổi tên"
		doc.save()
		self.assertEqual(frappe.db.get_value("Equipment", doc.name, "equipment_name"), "Đổi tên")

	def test_code_cannot_be_typed(self):
		doc = frappe.get_doc(
			{
				"doctype": "Equipment",
				"name": "TB-7777",
				"equipment_name": "Gõ tay",
				"equipment_type": "Dryer",
				"manufacturer": "M",
				"model": "X",
				"serial_no": "SN-TYPED",
				"zone_in": "ZONE-CLEAN",
				"purchase_value": 1,
				"depreciation_years": 1,
				"planned_loads_year": 1,
			}
		).insert()
		self.assertRegex(doc.name, r"^TB-\d{4}$")
		self.assertNotEqual(doc.name, "TB-7777")

	@bru("BRU-CST-001")
	def test_depreciation_per_load_formula(self):
		self.assertEqual(make_equipment().depreciation_per_load, 20000)
		self.assertEqual(
			make_equipment(serial="SN-R", purchase_value=1000000, years=3, loads=7).depreciation_per_load,
			47619,
		)
		# làm tròn nửa lên: 5 / 2 = 2.5 -> 3
		self.assertEqual(
			make_equipment(serial="SN-H", purchase_value=5, years=1, loads=2).depreciation_per_load, 3
		)
		self.assertEqual(make_equipment(serial="SN-Z", purchase_value=0).depreciation_per_load, 0)

	def test_depreciation_requires_positive_years_and_loads(self):
		with self.assertRaises(frappe.ValidationError):
			make_equipment(years=0)
		with self.assertRaises(frappe.ValidationError):
			make_equipment(loads=0)
		with self.assertRaises(frappe.ValidationError):
			make_equipment(purchase_value=-1)

	def test_serial_unique_case_and_space_insensitive(self):
		first = make_equipment(serial="SN-001")
		with self.assertRaises(frappe.ValidationError):
			make_equipment(serial="sn-001 ")
		with self.assertRaises(frappe.ValidationError):
			make_equipment(serial="   ")
		other = make_equipment(serial="  SN-002 ")
		self.assertEqual(other.serial_no, "SN-002")
		# sửa chính nó không tự va chạm
		first.manufacturer = "Khác"
		first.save()
		other.serial_no = "sn-001"
		with self.assertRaises(frappe.ValidationError):
			other.save()

	@bru("BRU-FLOW-001")
	def test_two_door_machine_must_exit_to_next_zone(self):
		make_equipment(serial="S1", zone_in="ZONE-CLEAN", zone_out="ZONE-STERILE")
		make_equipment(serial="S2", zone_in="ZONE-DIRTY", zone_out="ZONE-CLEAN")
		make_equipment(serial="S3", zone_in="ZONE-CLEAN", zone_out=None)
		with self.assertRaises(frappe.ValidationError):
			make_equipment(serial="S4", zone_in="ZONE-DIRTY", zone_out="ZONE-STERILE")
		with self.assertRaises(frappe.ValidationError):
			make_equipment(serial="S5", zone_in="ZONE-CLEAN", zone_out="ZONE-DIRTY")

	def test_zone_in_must_be_a_zone_not_a_station(self):
		with self.assertRaises(frappe.ValidationError):
			make_equipment(zone_in="TR-004", zone_out=None)

	def test_safe_range_min_not_above_max(self):
		make_equipment(serial="R1", safe_temp_min=121, safe_temp_max=134)
		make_equipment(serial="R2", safe_temp_min=121)
		with self.assertRaises(frappe.ValidationError):
			make_equipment(serial="R3", safe_temp_min=135, safe_temp_max=134)

	def test_equipment_type_cannot_change_after_creation(self):
		# norm_status / outside_safe_range lưu trên chương trình tính theo loại máy: máy không đổi loại
		self.assertEqual(frappe.get_meta("Equipment").get_field("equipment_type").set_only_once, 1)
		doc = make_equipment(serial="SN-TYPE")
		doc.equipment_type = "Dryer"
		with self.assertRaisesRegex(frappe.ValidationError, "Equipment Type cannot be changed"):
			doc.save()
		self.assertEqual(frappe.db.get_value("Equipment", doc.name, "equipment_type"), "Steam Sterilizer")

	@bru("BRU-EQP-003")
	def test_safe_range_change_recomputes_programs(self):
		from tracecore.tests.factories import make_program

		doc = make_equipment(serial="SN-RESAVE", safe_temp_min=105, safe_temp_max=140)
		program = make_program(doc.name, code="RS-137", temperature=137)
		other = make_program(doc.name, code="RS-121", temperature=121)
		self.assertEqual(program.outside_safe_range, 0)
		modified = frappe.db.get_value("Process Program", other.name, "modified")

		doc.reload()
		doc.equipment_name = "Đổi tên không đổi dải"
		doc.save()
		self.assertEqual(frappe.db.get_value("Process Program", other.name, "modified"), modified)

		audits = frappe.db.count("Audit Log", {"ref_doctype": "Process Program", "ref_name": program.name})
		doc.reload()
		doc.safe_temp_max = 135
		doc.save()
		self.assertEqual(frappe.db.get_value("Process Program", program.name, "outside_safe_range"), 1)
		self.assertEqual(frappe.db.get_value("Process Program", other.name, "outside_safe_range"), 0)
		self.assertGreater(
			frappe.db.count("Audit Log", {"ref_doctype": "Process Program", "ref_name": program.name}), audits
		)

		doc.reload()
		doc.safe_temp_max = 0
		doc.save()
		self.assertEqual(frappe.db.get_value("Process Program", program.name, "outside_safe_range"), 0)

	def test_safe_range_change_skips_program_that_cannot_be_saved(self):
		# chương trình không lưu lại được (ở đây: dòng định mức mặc định đã mất) → ghi Error Log, máy vẫn lưu
		from tracecore.equipment.tests.test_norms import make_type_norm
		from tracecore.tests.factories import make_program

		make_type_norm()
		doc = make_equipment(serial="SN-SKIP", safe_temp_max=140)
		broken = make_program(doc.name, code="SK-DEF", temperature=137, use_default_norms=1)
		program = make_program(doc.name, code="SK-137", temperature=137)
		frappe.db.delete("Equipment Type Norm", {"name": "Steam Sterilizer"})
		errors = frappe.db.count("Error Log")

		doc.reload()
		doc.safe_temp_max = 135
		doc.save()
		self.assertEqual(frappe.db.get_value("Equipment", doc.name, "safe_temp_max"), 135)
		self.assertEqual(frappe.db.get_value("Process Program", program.name, "outside_safe_range"), 1)
		self.assertEqual(frappe.db.get_value("Process Program", broken.name, "outside_safe_range"), 0)
		self.assertEqual(frappe.db.count("Error Log"), errors + 1)

	def test_status_defaults_ready_and_cannot_be_edited_directly(self):
		doc = make_equipment()
		self.assertEqual(doc.status, "Ready")
		self.assertEqual(frappe.get_meta("Equipment").get_field("status").read_only, 1)
		doc.status = "Locked"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		with self.assertRaises(frappe.ValidationError):
			make_equipment(serial="N1", status="Repair")

	def test_set_status_retired_requires_reason_and_is_audited(self):
		doc = make_equipment()
		for reason in (None, "", "   "):
			with self.assertRaises(frappe.ValidationError):
				set_status(doc.name, "Retired", reason)
		set_status(doc.name, "Locked")
		set_status(doc.name, "Retired", "Hỏng không sửa được")
		doc.reload()
		self.assertEqual(doc.status, "Retired")
		self.assertEqual(doc.retired_reason, "Hỏng không sửa được")
		self.assertTrue(doc.retired_on)
		logs = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Equipment", "ref_name": doc.name, "action": "Update"},
			fields=["old_value", "new_value"],
			order_by="creation asc",
		)
		changes = [
			(frappe.parse_json(r.old_value).get("status"), frappe.parse_json(r.new_value).get("status"))
			for r in logs
		]
		self.assertIn(("Ready", "Locked"), changes)
		self.assertIn(("Locked", "Retired"), changes)

	def test_retired_cannot_return(self):
		doc = make_equipment()
		set_status(doc.name, "Retired", "Hết niên hạn")
		for status in ("Ready", "Locked", "Repair"):
			with self.assertRaises(frappe.ValidationError):
				set_status(doc.name, status)
		with self.assertRaises(frappe.ValidationError):
			set_status(make_equipment(serial="X").name, "Bogus")

	def test_equipment_cannot_be_deleted(self):
		doc = make_equipment()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Equipment", doc.name, force=True)
		self.assertTrue(frappe.db.exists("Equipment", doc.name))

	def test_permissions_match_q7(self):
		validate_permissions_for_doctype("Equipment")
		perms = {row.role: row for row in frappe.get_meta("Equipment").permissions}
		for role in ("System Manager", "TC R10"):
			for right in ("read", "write", "create", "report"):
				self.assertEqual(perms[role].get(right), 1, msg=(role, right))
		for role in ("TC R01", "TC R02", "TC R03", "TC R04", "TC R05", "TC R06", "TC R09"):
			self.assertEqual(perms[role].read, 1, msg=role)
			self.assertFalse(perms[role].write or perms[role].create, msg=role)
		self.assertFalse(any(row.delete for row in perms.values()))

	def test_asset_is_optional(self):
		doc = make_equipment()
		self.assertFalse(doc.asset)
		self.assertEqual(frappe.get_meta("Equipment").get_field("asset").reqd, 0)
