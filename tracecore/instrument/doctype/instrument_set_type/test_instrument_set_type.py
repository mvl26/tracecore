import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import gs1
from tracecore.tests.factories import make_item, make_pack, make_set_type, make_set_unit

# Department/Item (ERPNext) kéo theo test record Company → Warehouse… cần Setup Wizard;
# site CI mới chưa chạy wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Department", "Item"]

GTIN_OK = "09520000000011"
GTIN_BAD_CHECK_DIGIT = "09520000000012"


class TestInstrumentSetType(FrappeTestCase):
	def setUp(self):
		# FrappeTestCase chỉ rollback theo lớp; các test GTIN dùng cùng giá trị nên cô lập từng test
		frappe.db.savepoint("tc_set_type_test")

	def tearDown(self):
		frappe.db.rollback(save_point="tc_set_type_test")

	def test_set_type_code_validation(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Instrument Set Type",
					"type_code": "bpt 1",
					"set_type_name": "X",
					"method": "Steam",
				}
			).insert()

		doc = frappe.get_doc(
			{
				"doctype": "Instrument Set Type",
				"type_code": "zz9t",
				"set_type_name": "Bo test",
				"method": "Plasma",
			}
		).insert()
		self.assertEqual(doc.name, "ZZ9T")
		self.assertEqual(doc.type_code, "ZZ9T")

	def test_gtin_must_be_valid_gtin14(self):
		self.assertTrue(gs1.is_valid_gtin14(GTIN_OK))
		for index, bad in enumerate((GTIN_BAD_CHECK_DIGIT, "123", "0952000000001A", "095200000000111")):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				make_set_type(f"GV{index}", gtin=bad)
		doc = make_set_type("GVOK", gtin=GTIN_OK)
		self.assertEqual(frappe.db.get_value("Instrument Set Type", doc.name, "gtin"), GTIN_OK)

	def test_gtin_whitespace_is_stripped(self):
		doc = make_set_type("GVWS", gtin=f"  {GTIN_OK}  ")
		self.assertEqual(frappe.db.get_value("Instrument Set Type", doc.name, "gtin"), GTIN_OK)

	def test_gtin_unique(self):
		make_set_type("GUA", gtin=GTIN_OK)
		with self.assertRaises(frappe.ValidationError):
			make_set_type("GUB", gtin=GTIN_OK)
		self.assertFalse(frappe.db.exists("Instrument Set Type", "GUB"))

	def test_gtin_unique_on_update(self):
		other = "09520000000028"
		self.assertTrue(gs1.is_valid_gtin14(other))
		make_set_type("GUC", gtin=GTIN_OK)
		second = make_set_type("GUD", gtin=other)
		second.gtin = GTIN_OK
		with self.assertRaises(frappe.ValidationError):
			second.save()

	def test_gtin_optional_until_packing(self):
		first = make_set_type("GOA", gtin=None)
		second = make_set_type("GOB", gtin=None)
		blank = frappe.get_doc(
			{
				"doctype": "Instrument Set Type",
				"type_code": "GOC",
				"set_type_name": "Blank GTIN",
				"method": "Steam",
				"gtin": "",
			}
		).insert()
		for doc in (first, second, blank):
			self.assertFalse(frappe.db.get_value("Instrument Set Type", doc.name, "gtin"), msg=doc.name)

	def test_auto_gtin_is_unused_valid_test_gtin(self):
		first = make_set_type("GAA")
		second = make_set_type("GAB")
		self.assertTrue(gs1.is_valid_gtin14(first.gtin) and gs1.is_test_gtin(first.gtin))
		self.assertTrue(gs1.is_valid_gtin14(second.gtin) and gs1.is_test_gtin(second.gtin))
		self.assertNotEqual(first.gtin, second.gtin)

	def test_shelf_life_override_not_negative(self):
		with self.assertRaises(frappe.ValidationError):
			make_set_type("SLN", shelf_life_days=-1)
		self.assertFalse(frappe.db.exists("Instrument Set Type", "SLN"))
		self.assertEqual(make_set_type("SL0", shelf_life_days=0).shelf_life_days, 0)
		self.assertEqual(make_set_type("SL30", shelf_life_days=30).shelf_life_days, 30)

	def test_packing_fields_are_stored(self):
		make_item("VT-GOI-ST", "Packaging", method="Steam", shelf_life_days=180)
		doc = make_set_type(
			"PKF", default_pack_type="VT-GOI-ST", shelf_life_days=90, tray_image="/files/tray-pkf.png"
		)
		row = frappe.db.get_value(
			"Instrument Set Type",
			doc.name,
			["default_pack_type", "shelf_life_days", "tray_image", "current_bom_version", "department"],
			as_dict=True,
		)
		self.assertEqual(row.default_pack_type, "VT-GOI-ST")
		self.assertEqual(row.shelf_life_days, 90)
		self.assertEqual(row.tray_image, "/files/tray-pkf.png")
		self.assertEqual(row.current_bom_version, 1)
		self.assertFalse(row.department)

	def test_gtin_locked_after_pack(self):
		set_type = make_set_type("GLK", gtin=GTIN_OK)
		make_pack(make_set_unit(set_type.name))

		set_type.gtin = "09520000000028"
		with self.assertRaises(frappe.ValidationError):
			set_type.save()
		set_type.gtin = None
		with self.assertRaises(frappe.ValidationError):
			set_type.save()
		self.assertEqual(frappe.db.get_value("Instrument Set Type", "GLK", "gtin"), GTIN_OK)

		# trường khác vẫn sửa được, và lưu lại đúng GTIN cũ (kể cả có khoảng trắng) không bị chặn
		set_type = frappe.get_doc("Instrument Set Type", "GLK")
		set_type.set_type_name = "Renamed after pack"
		set_type.gtin = f" {GTIN_OK} "
		set_type.save()
		self.assertEqual(
			frappe.db.get_value("Instrument Set Type", "GLK", "set_type_name"), "Renamed after pack"
		)

	def test_gtin_still_editable_for_other_set_types_without_pack(self):
		locked = make_set_type("GLA", gtin=GTIN_OK)
		make_pack(make_set_unit(locked.name))
		free = make_set_type("GLB", gtin="09520000000028")
		free.gtin = "09520000000035"
		self.assertTrue(gs1.is_valid_gtin14(free.gtin))
		free.save()
		self.assertEqual(frappe.db.get_value("Instrument Set Type", "GLB", "gtin"), "09520000000035")
