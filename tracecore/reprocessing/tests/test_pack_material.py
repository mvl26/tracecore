"""A-122 (FEAT-086): nhóm vật liệu gói và loại gói mặc định của bộ ở T4."""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.patches.v0_1 import a122_pack_material
from tracecore.reprocessing import packing
from tracecore.tests.factories import make_item, make_set_type
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _material(item, value):
	frappe.db.set_value("Item", item, "tc_pack_material", value)
	return item


class TestPackMaterialField(IsolatedTestCase):
	def test_item_has_pack_material_select_for_packaging(self):
		field = frappe.get_meta("Item").get_field("tc_pack_material")
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Select")
		self.assertEqual(
			[o for o in field.options.split("\n") if o], ["Rigid Container", "Sealed Pouch", "Wrap"]
		)
		self.assertIn("Packaging", field.depends_on)


class TestPackTypesMaterial(IsolatedTestCase):
	def test_pack_types_carry_material_and_default_flag(self):
		box = _material(
			make_item("VT-GOI-HOP-A122", "Packaging", shelf_life_days=180).name, "Rigid Container"
		)
		pouch = _material(make_item("VT-GOI-TUI-A122", "Packaging", shelf_life_days=180).name, "Sealed Pouch")
		loose = make_item("VT-GOI-KHAC-A122", "Packaging", shelf_life_days=30).name
		set_type = make_set_type("A122D", default_pack_type=pouch)

		rows = {row["item"]: row for row in packing.pack_types(set_type.name)}

		self.assertEqual(rows[box]["material"], "Rigid Container")
		self.assertEqual(rows[pouch]["material"], "Sealed Pouch")
		self.assertEqual(rows[loose]["material"], "")
		self.assertTrue(rows[pouch]["is_default"])
		self.assertFalse(rows[box]["is_default"])
		self.assertEqual(packing.pack_types(set_type.name)[0]["item"], pouch)

	@bru("BRU-REP-009")
	def test_server_still_refuses_a_pack_type_of_another_method(self):
		plasma = _material(
			make_item("VT-GOI-TYVEK-A122", "Packaging", method="Plasma", shelf_life_days=180).name,
			"Sealed Pouch",
		)
		self.assertNotIn(
			plasma, [row["item"] for row in packing.pack_types(make_set_type("A122S", method="Steam").name)]
		)
		with self.assertRaises(BlockedError) as caught:
			packing.check_pack_method(plasma, "Steam")
		self.assertEqual(caught.exception.block.code, "PACK_TYPE_INVALID")


class TestPackMaterialPatch(IsolatedTestCase):
	def test_patch_classifies_blank_packaging_by_code_then_name(self):
		codes = {
			"PK-HOP-FILTER-A122": "Rigid Container",
			"PK-TUI-GN-A122": "Sealed Pouch",
			"PK-VKD-SMS-A122": "Wrap",
			"PK-XV-A122": "Wrap",
		}
		for code in codes:
			make_item(code, "Packaging", shelf_life_days=30)
		named = make_item("VT-A122-NAMED", "Packaging", shelf_life_days=30).name
		frappe.db.set_value("Item", named, "item_name", "Giấy crepe gói bộ")
		unknown = make_item("VT-A122-LA", "Packaging", shelf_life_days=30).name
		kept = _material(make_item("PK-TUI-KEPT-A122", "Packaging", shelf_life_days=30).name, "Wrap")
		label = make_item("PK-HOP-NHAN-A122", "Label", method="Steam").name

		a122_pack_material.execute()
		a122_pack_material.execute()  # chạy lại không đổi gì thêm

		value = lambda code: frappe.db.get_value("Item", code, "tc_pack_material") or ""  # noqa: E731
		for code, material in codes.items():
			self.assertEqual(value(code), material, code)
		self.assertEqual(value(named), "Wrap")
		self.assertEqual(value(unknown), "")
		self.assertEqual(value(kept), "Wrap")
		self.assertEqual(value(label), "")

	def test_classify_rules(self):
		classify = a122_pack_material.classify
		self.assertEqual(classify("X1", "Hộp hấp có phin lọc"), "Rigid Container")
		self.assertEqual(classify("X2", "Túi ép Tyvek"), "Sealed Pouch")
		self.assertEqual(classify("X3", "Xăng vải 2 lớp"), "Wrap")
		self.assertEqual(classify("X4", "Vải không dệt SMS"), "Wrap")
		self.assertEqual(classify("X5", "Lá nhôm"), None)
