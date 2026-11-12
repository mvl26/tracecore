"""A-155 (FEAT-097): loại vật liệu đóng gói — giấy bọc, kích thước túi ép, số lớp giấy bọc."""

import frappe

from tracecore.inventory import items
from tracecore.inventory.tests.test_items import new_item
from tracecore.patches.v0_1 import a155_pack_material_detail
from tracecore.reprocessing import packing
from tracecore.tests.factories import make_item, make_set_type
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _value(code, field):
	return frappe.db.get_value("Item", code, field) or ""


class TestPackMaterialFields(IsolatedTestCase):
	def test_material_options_include_paper_wrap(self):  # AC-097-01
		meta = frappe.get_meta("Item")
		options = [o for o in meta.get_field("tc_pack_material").options.split("\n") if o]
		self.assertEqual(options, ["Rigid Container", "Sealed Pouch", "Wrap", "Paper Wrap"])

	def test_pouch_size_and_layers_fields_depend_on_material(self):
		meta = frappe.get_meta("Item")
		size = meta.get_field("tc_pouch_size")
		layers = meta.get_field("tc_wrap_layers")
		self.assertEqual(size.fieldtype, "Data")
		self.assertIn("Sealed Pouch", size.depends_on)
		self.assertIn("Sealed Pouch", size.mandatory_depends_on)
		self.assertEqual(layers.fieldtype, "Select")
		self.assertEqual([o for o in layers.options.split("\n") if o], ["Single Layer", "Double Layer"])
		self.assertIn("Paper Wrap", layers.depends_on)
		self.assertIn("Paper Wrap", layers.mandatory_depends_on)


class TestPouchSizeParse(IsolatedTestCase):
	def test_accepts_width_by_length_or_width_only(self):
		parse = items.normalize_pouch_size
		self.assertEqual(parse("100x250"), "100 \u00d7 250")
		self.assertEqual(parse(" 100 X 250 mm "), "100 \u00d7 250")
		self.assertEqual(parse("100*250mm"), "100 \u00d7 250")
		self.assertEqual(parse("100 \u00d7 250"), "100 \u00d7 250")
		self.assertEqual(parse("200"), "200")
		self.assertEqual(parse("200 mm"), "200")

	def test_rejects_bad_sizes(self):
		parse = items.normalize_pouch_size
		for raw in ("", "abc", "5x250", "100x2000", "100x250x3", "10,5x20", "-100"):
			self.assertIsNone(parse(raw), raw)


class TestPackMaterialValidate(IsolatedTestCase):
	def test_pouch_requires_a_valid_size_and_is_normalized(self):  # AC-097-02
		with self.assertRaises(frappe.ValidationError) as ctx:
			new_item("F97-TUI-1", "Packaging", tc_pack_material="Sealed Pouch").insert(
				ignore_permissions=True
			)
		self.assertIn("size", str(ctx.exception).lower())
		with self.assertRaises(frappe.ValidationError):
			new_item("F97-TUI-2", "Packaging", tc_pack_material="Sealed Pouch", tc_pouch_size="to").insert(
				ignore_permissions=True
			)
		ok = new_item("F97-TUI-3", "Packaging", tc_pack_material="Sealed Pouch", tc_pouch_size="100x250mm")
		ok.insert(ignore_permissions=True)
		self.assertEqual(_value(ok.name, "tc_pouch_size"), "100 \u00d7 250")

	def test_paper_wrap_requires_layers(self):  # AC-097-03
		with self.assertRaises(frappe.ValidationError) as ctx:
			new_item("F97-GIAY-1", "Packaging", tc_pack_material="Paper Wrap").insert(ignore_permissions=True)
		self.assertIn("layer", str(ctx.exception).lower())
		ok = new_item("F97-GIAY-2", "Packaging", tc_pack_material="Paper Wrap", tc_wrap_layers="Double Layer")
		ok.insert(ignore_permissions=True)
		self.assertEqual(_value(ok.name, "tc_wrap_layers"), "Double Layer")

	def test_fields_that_do_not_apply_are_cleared(self):  # AC-097-04
		doc = new_item(
			"F97-HOP-1",
			"Packaging",
			tc_pack_material="Rigid Container",
			tc_pouch_size="100x250",
			tc_wrap_layers="Single Layer",
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(_value(doc.name, "tc_pouch_size"), "")
		self.assertEqual(_value(doc.name, "tc_wrap_layers"), "")

	def test_material_only_for_packaging_items(self):  # AC-097-04
		with self.assertRaises(frappe.ValidationError):
			new_item("F97-KHAC-1", "Other", tc_pack_material="Wrap").insert(ignore_permissions=True)

	def test_other_materials_and_blank_still_save(self):
		new_item("F97-VAI-1", "Packaging", tc_pack_material="Wrap").insert(ignore_permissions=True)
		new_item("F97-TRONG-1", "Packaging").insert(ignore_permissions=True)


class TestPackTypesDetail(IsolatedTestCase):
	def test_pack_types_carry_size_and_layers(self):  # AC-097-05
		pouch = make_item("VT-GOI-TUI-A155", "Packaging", shelf_life_days=180).name
		paper = make_item("VT-GOI-GIAY-A155", "Packaging", shelf_life_days=30).name
		frappe.db.set_value(
			"Item", pouch, {"tc_pack_material": "Sealed Pouch", "tc_pouch_size": "100 \u00d7 250"}
		)
		frappe.db.set_value(
			"Item", paper, {"tc_pack_material": "Paper Wrap", "tc_wrap_layers": "Double Layer"}
		)
		set_type = make_set_type("A155D", default_pack_type=pouch)

		rows = {row["item"]: row for row in packing.pack_types(set_type.name)}

		self.assertEqual(rows[pouch]["pouch_size"], "100 \u00d7 250")
		self.assertEqual(rows[pouch]["wrap_layers"], "")
		self.assertEqual(rows[paper]["material"], "Paper Wrap")
		self.assertEqual(rows[paper]["wrap_layers"], "Double Layer")
		self.assertEqual(rows[paper]["pouch_size"], "")


class TestPackMaterialDetailPatch(IsolatedTestCase):
	def test_patch_moves_paper_and_infers_from_names(self):  # AC-097-06
		def item(code, name, material=None):
			made = make_item(code, "Packaging", shelf_life_days=30).name
			frappe.db.set_value("Item", made, {"item_name": name, "tc_pack_material": material})
			return made

		crepe = item("VT-A155-CREPE", "Giấy crepe gói bộ 2 lớp", "Wrap")
		paper = item("VT-A155-PAPER", "Giấy gói 1 lớp")
		cloth = item("VT-A155-VAI", "Xăng vải 2 lớp", "Wrap")
		pouch = item("VT-A155-TUI", "Túi ép phẳng 100x250 mm", "Sealed Pouch")
		roll = item("VT-A155-CUON", "Túi ép dạng cuộn", "Sealed Pouch")
		kept = item("VT-A155-KEPT", "Giấy crepe", "Paper Wrap")
		frappe.db.set_value("Item", kept, "tc_wrap_layers", "Single Layer")
		other = make_item("VT-A155-NHAN", "Label", method="Steam").name
		frappe.db.set_value("Item", other, "item_name", "Giấy nhãn")

		a155_pack_material_detail.execute()
		a155_pack_material_detail.execute()  # chạy lại không đổi thêm

		self.assertEqual(_value(crepe, "tc_pack_material"), "Paper Wrap")
		self.assertEqual(_value(crepe, "tc_wrap_layers"), "Double Layer")
		self.assertEqual(_value(paper, "tc_pack_material"), "Paper Wrap")
		self.assertEqual(_value(paper, "tc_wrap_layers"), "Single Layer")
		self.assertEqual(_value(cloth, "tc_pack_material"), "Wrap")
		self.assertEqual(_value(cloth, "tc_wrap_layers"), "")
		self.assertEqual(_value(pouch, "tc_pouch_size"), "100 \u00d7 250")
		self.assertEqual(_value(roll, "tc_pouch_size"), "")
		self.assertEqual(_value(kept, "tc_wrap_layers"), "Single Layer")
		self.assertEqual(_value(other, "tc_pack_material"), "")
