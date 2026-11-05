"""A-122 (FEAT-086): nhóm vật liệu gói và loại gói mặc định của bộ ở T4."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core.errors import BlockedError
from tracecore.patches.v0_1 import a122_pack_material
from tracecore.reprocessing import packing
from tracecore.tests.factories import make_batch, make_item, make_set_type
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestDefaultIndicatorLots(IsolatedTestCase):
	"""A-122 (g): lô của chỉ thị mặc định của loại bộ đứng đầu danh sách ở T4, không chọn sẵn."""

	def _lot(self, item, batch, days):
		return make_batch(item, batch, expiry_date=add_days(today(), days)).name

	@bru("BRU-REP-013")
	def test_lots_of_the_default_item_come_first(self):
		usual = make_item("CI5-A122-USUAL", "Chemical Indicator", method="Steam", ci_class="5").name
		chosen = make_item("CI6-A122-CHOSEN", "Chemical Indicator", method="Steam", ci_class="6").name
		near = self._lot(usual, "LOT-A122-NEAR", 2)
		late = self._lot(chosen, "LOT-A122-LATE", 300)
		later = self._lot(chosen, "LOT-A122-LATER", 400)

		rows = packing.ci_lots("Steam", getdate(), chosen)

		self.assertEqual([row["batch"] for row in rows[:2]], [late, later])
		self.assertTrue(all(row["is_default"] for row in rows[:2]))
		self.assertIn(near, [row["batch"] for row in rows])
		self.assertFalse(next(row for row in rows if row["batch"] == near)["is_default"])
		self.assertLessEqual(len(rows), packing.CI_LOT_LIMIT)

	def test_without_default_the_order_is_unchanged(self):
		usual = make_item("CI5-A122-PLAIN", "Chemical Indicator", method="Steam", ci_class="5").name
		self._lot(usual, "LOT-A122-PLAIN", 3)
		self.assertEqual(packing.ci_lots("Steam", getdate()), packing.ci_lots("Steam", getdate(), None))
		self.assertFalse(any(row["is_default"] for row in packing.ci_lots("Steam", getdate())))

	def test_context_carries_the_default_item_and_does_not_pick_a_lot(self):
		ci = make_item("CI5-A122-CTX", "Chemical Indicator", method="Steam", ci_class="5").name
		set_type = make_set_type("A122X", method="Steam")
		set_type.default_ci_item = ci
		set_type.save(ignore_permissions=True)
		block = packing.ci_block(frappe.get_doc("Instrument Set Type", set_type.name))
		self.assertEqual(block["default_item"], ci)
		self.assertNotIn("batch", block)


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
