import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

from tracecore.equipment import norms
from tracecore.equipment.status import set_status
from tracecore.tests.factories import make_equipment, make_item, make_program
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Asset", "Item", "User"]

MISSING_WARNING = "costing is not calculated"


def make_type_norm(equipment_type="Steam Sterilizer", **values):
	return frappe.get_doc(
		{
			"doctype": "Equipment Type Norm",
			"equipment_type": equipment_type,
			**{"duration_min": 30, "kwh_per_cycle": 9, "water_l_per_cycle": 40, "steam_kg_per_cycle": 6},
			**values,
		}
	).insert()


def messages():
	return [frappe.parse_json(m).get("message") for m in frappe.local.message_log]


def consumable(code="NM-CI-1"):
	return [{"item": make_item(code, "Chemical Indicator").name, "qty_per_load": 1}]


class TestNorms(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.steam = make_equipment()
		self.plasma = make_equipment(name="Máy plasma", equipment_type="Plasma Sterilizer", serial="SN-PL")
		frappe.local.message_log = []

	@bru("BRU-EQP-003")
	def test_norm_status_complete(self):
		doc = make_program(self.steam.name, code="NC-1", water=40, consumables=consumable())
		self.assertEqual(doc.norm_status, "Complete")
		self.assertEqual(norms.norm_status(doc), "Complete")
		self.assertFalse([m for m in messages() if MISSING_WARNING in m])

	@bru("BRU-EQP-003")
	def test_norm_status_missing_blocks_costing_flag(self):
		no_kwh = make_program(self.steam.name, code="NM-1", kwh=0, water=40, consumables=consumable())
		self.assertEqual(no_kwh.norm_status, "Missing")
		no_cons = make_program(self.plasma.name, code="NM-2")
		self.assertEqual(no_cons.norm_status, "Missing")
		no_min = make_program(self.plasma.name, code="NM-3", minutes=0, consumables=consumable())
		self.assertEqual(no_min.norm_status, "Missing")

	def test_water_required_only_for_water_equipment_types(self):
		self.assertEqual(
			norms.WATER_EQUIPMENT_TYPES,
			("Steam Sterilizer", "Washer-Disinfector", "Laundry Washer", "Ultrasonic Cleaner"),
		)
		self.assertEqual(
			make_program(self.steam.name, code="W-1", consumables=consumable()).norm_status, "Missing"
		)
		self.assertEqual(
			make_program(self.plasma.name, code="W-2", consumables=consumable()).norm_status, "Complete"
		)

	def test_default_norms_fill_only_missing_values(self):
		make_type_norm()
		doc = make_program(
			self.steam.name, code="D-1", kwh=5, minutes=0, consumables=consumable(), use_default_norms=1
		)
		self.assertEqual(doc.kwh_per_cycle, 5)
		self.assertEqual(doc.duration_min, 30)
		self.assertEqual(doc.water_l_per_cycle, 40)
		self.assertEqual(doc.steam_kg_per_cycle, 6)
		self.assertEqual(doc.norm_status, "Default")
		# lưu lại không làm trạng thái nhảy sang Complete
		doc.save()
		self.assertEqual(doc.norm_status, "Default")

	def test_default_norms_never_default_consumables(self):
		make_type_norm()
		doc = make_program(self.steam.name, code="D-2", use_default_norms=1)
		self.assertEqual(doc.norm_status, "Missing")
		self.assertEqual(len(doc.consumables), 0)
		doc.append("consumables", consumable("NM-CI-2")[0])
		doc.save()
		self.assertEqual(doc.norm_status, "Default")
		self.assertEqual(doc.water_l_per_cycle, 40)

	def test_apply_default_and_default_norm(self):
		self.assertIsNone(norms.default_norm("Steam Sterilizer"))
		make_type_norm()
		self.assertEqual(
			norms.default_norm("Steam Sterilizer"),
			{"duration_min": 30, "kwh_per_cycle": 9, "water_l_per_cycle": 40, "steam_kg_per_cycle": 6},
		)
		doc = frappe.new_doc("Process Program")
		doc.equipment = self.steam.name
		doc.kwh_per_cycle = 2
		norms.apply_default(doc)
		self.assertEqual((doc.kwh_per_cycle, doc.duration_min, doc.water_l_per_cycle), (2, 30, 40))

	def test_use_default_requires_a_type_norm(self):
		with self.assertRaises(frappe.ValidationError):
			make_program(self.steam.name, code="U-1", use_default_norms=1, consumables=consumable())
		make_type_norm("Plasma Sterilizer", water_l_per_cycle=0)
		with self.assertRaises(frappe.ValidationError):
			make_program(self.steam.name, code="U-2", use_default_norms=1)

	def test_missing_norm_warning_message(self):
		doc = make_program(self.steam.name, code="MW-1")
		self.assertEqual(doc.norm_status, "Missing")
		found = [m for m in messages() if MISSING_WARNING in m]
		self.assertEqual(len(found), 1)
		self.assertIn("MW-1", found[0])
		# mỗi lần lưu cảnh báo một lần
		frappe.local.message_log = []
		doc.save()
		self.assertEqual(len([m for m in messages() if MISSING_WARNING in m]), 1)

	@bru("BRU-EQP-003")
	def test_outside_safe_range_warns_but_saves(self):
		eq = make_equipment(
			name="Máy dải", serial="SN-RANGE", safe_temp_min=105, safe_temp_max=140, safe_pressure_max=3
		)
		doc = make_program(eq.name, code="R-1", temperature=150, pressure=2)
		self.assertEqual(doc.outside_safe_range, 1)
		warn = [m for m in messages() if "150" in m]
		self.assertEqual(len(warn), 1)
		self.assertIn("R-1", warn[0])
		self.assertIn("140", warn[0])
		low = make_program(eq.name, code="R-2", temperature=100)
		self.assertEqual(low.outside_safe_range, 1)
		pressure = make_program(eq.name, code="R-3", temperature=121, pressure=4)
		self.assertEqual(pressure.outside_safe_range, 1)
		ok = make_program(eq.name, code="R-4", temperature=134, pressure=3)
		self.assertEqual(ok.outside_safe_range, 0)
		# sửa về trong dải thì cờ tắt
		doc.temperature = 121
		doc.save()
		self.assertEqual(doc.outside_safe_range, 0)

	def test_no_range_means_no_check(self):
		doc = make_program(self.steam.name, code="NR-1", temperature=999, pressure=99)
		self.assertEqual(doc.outside_safe_range, 0)
		self.assertEqual(norms.range_warnings(doc, self.steam), [])

	def test_range_warnings_ignores_unset_values(self):
		eq = make_equipment(name="Máy dải 2", serial="SN-RANGE2", safe_temp_min=105, safe_temp_max=140)
		doc = make_program(eq.name, code="NR-2")  # chưa đặt nhiệt độ
		self.assertEqual(doc.outside_safe_range, 0)

	def test_equipment_type_norm_one_row_per_type(self):
		make_type_norm()
		with self.assertRaises(frappe.DuplicateEntryError):
			make_type_norm()
		with self.assertRaises(frappe.ValidationError):
			make_type_norm("Dryer", kwh_per_cycle=-1)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Equipment Type Norm", "Steam Sterilizer", force=True)

	def test_equipment_type_norm_permissions(self):
		validate_permissions_for_doctype("Equipment Type Norm")
		perms = {row.role: row for row in frappe.get_meta("Equipment Type Norm").permissions}
		for role in ("System Manager", "TC R10"):
			for right in ("read", "write", "create", "report"):
				self.assertEqual(perms[role].get(right), 1, msg=(role, right))
		for role in ("TC R01", "TC R02", "TC R09"):
			self.assertEqual(perms[role].read, 1, msg=role)
			self.assertFalse(perms[role].write or perms[role].create, msg=role)
		self.assertFalse(any(row.delete for row in perms.values()))

	def test_r02_cannot_set_use_default_norms(self):
		make_type_norm()
		doc = make_program(self.steam.name, code="P1-1", consumables=consumable())
		user = "r02.norms@test.local"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{"doctype": "User", "email": user, "first_name": "R02", "roles": [{"role": "TC R02"}]}
			).insert(ignore_permissions=True)
		doc.reload()
		doc.use_default_norms = 1
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				doc.save()
		finally:
			frappe.set_user("Administrator")

	def test_reactivating_program_on_retired_equipment_rejected(self):
		doc = make_program(self.steam.name, code="RE-1")
		doc.is_active = 0
		doc.save()
		set_status(self.steam.name, "Retired", "Hết đời")
		doc.reload()
		doc.is_active = 1
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.program_name = "Đổi tên"  # vẫn sửa được khi giữ ngừng dùng
		doc.save()
