import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from tracecore.tests import factories

# Item/Batch (ERPNext) kéo theo test record Company → Warehouse, cần ERPNext đã chạy Setup Wizard;
# test này tự tạo dữ liệu qua factories nên bỏ phụ thuộc đó (site CI mới chưa có wizard).
test_ignore = ["Item", "Batch"]

CUSTOM_FIELDS = ("tc_item_group_cssd", "tc_compatible_method", "tc_ci_class", "tc_shelf_life_days")


class TestItemFields(FrappeTestCase):
	def test_item_custom_fields_installed(self):
		meta = frappe.get_meta("Item")
		fields = {name: meta.get_field(name) for name in CUSTOM_FIELDS}
		self.assertTrue(all(fields.values()), msg=fields)

		self.assertEqual(fields["tc_item_group_cssd"].fieldtype, "Select")
		self.assertEqual(
			fields["tc_item_group_cssd"].options, "\nPackaging\nChemical Indicator\nLabel\nLubricant"
		)
		self.assertEqual(fields["tc_compatible_method"].fieldtype, "Select")
		self.assertEqual(fields["tc_compatible_method"].options, "\nSteam\nPlasma")
		self.assertEqual(fields["tc_ci_class"].fieldtype, "Select")
		self.assertEqual(fields["tc_ci_class"].options, "\n1\n2\n4\n5\n6")
		self.assertEqual(fields["tc_shelf_life_days"].fieldtype, "Int")
		self.assertEqual(fields["tc_shelf_life_days"].depends_on, "eval:doc.tc_item_group_cssd=='Packaging'")

		labels = {name: field.label for name, field in fields.items()}
		self.assertEqual(
			labels,
			{
				"tc_item_group_cssd": "CSSD Item Group",
				"tc_compatible_method": "Compatible Method",
				"tc_ci_class": "Chemical Indicator Class",
				"tc_shelf_life_days": "Shelf Life (Days)",
			},
		)

	def test_item_custom_fields_follow_item_group(self):
		"""Bốn trường nằm liền sau item_group theo đúng thứ tự (insert_after dây chuyền)."""
		names = [field.fieldname for field in frappe.get_meta("Item").fields]
		start = names.index("item_group") + 1
		self.assertEqual(tuple(names[start : start + len(CUSTOM_FIELDS)]), CUSTOM_FIELDS)

	def test_shelf_life_is_separate_from_erpnext_batch_shelf_life(self):
		"""tc_shelf_life_days là hạn lưu của loại gói, không dùng shelf_life_in_days (hạn lô của vật tư)."""
		meta = frappe.get_meta("Item")
		erpnext_field, pack_field = meta.get_field("shelf_life_in_days"), meta.get_field("tc_shelf_life_days")
		self.assertTrue(erpnext_field and pack_field)
		self.assertNotEqual(pack_field.fieldname, erpnext_field.fieldname)
		self.assertEqual(erpnext_field.fieldtype, "Int")
		# trường chuẩn của ERPNext không bị ta đổi (không ẩn theo nhóm CSSD)
		self.assertFalse(erpnext_field.depends_on and "tc_item_group_cssd" in erpnext_field.depends_on)

	def test_ensure_item_masters_is_idempotent(self):
		factories.ensure_item_masters()
		factories.ensure_item_masters()
		self.assertTrue(frappe.db.exists("UOM", "Nos"))
		self.assertEqual(frappe.db.get_value("Item Group", "All Item Groups", "is_group"), 1)

	def test_factories_create_items_and_batches(self):
		label = factories.make_item("VT-NHAN-HAP", "Label", method="Steam")
		self.assertEqual(label.tc_compatible_method, "Steam")
		self.assertEqual(label.tc_item_group_cssd, "Label")
		self.assertEqual(
			(label.stock_uom, label.item_group, label.is_stock_item), ("Nos", "All Item Groups", 1)
		)

		indicator = factories.make_item(
			"CI5-STEAM", "Chemical Indicator", method="Steam", ci_class="5", has_batch_no=0
		)
		self.assertEqual(indicator.tc_ci_class, "5")
		self.assertEqual(indicator.has_batch_no, 0)

		expiry = add_days(today(), 30)
		batch = factories.make_batch("CI5-STEAM", "LOT-A", expiry_date=expiry)
		self.assertEqual(batch.item, "CI5-STEAM")
		self.assertEqual(batch.name, "LOT-A")
		self.assertEqual(getdate(batch.expiry_date), getdate(expiry))
		self.assertEqual(frappe.db.get_value("Item", "CI5-STEAM", "has_batch_no"), 1)

	def test_make_item_stores_pack_type_shelf_life(self):
		pack = factories.make_item("GOI-VAI-60", "Packaging", method="Steam", shelf_life_days=180)
		self.assertEqual(frappe.db.get_value("Item", pack.name, "tc_shelf_life_days"), 180)

	def test_factories_are_idempotent(self):
		first = factories.make_item("VT-DAU-BT", "Lubricant", has_batch_no=1)
		second = factories.make_item("VT-DAU-BT", "Lubricant", has_batch_no=1)
		self.assertEqual(first.name, second.name)
		self.assertEqual(frappe.db.count("Item", {"item_code": "VT-DAU-BT"}), 1)

		lot = factories.make_batch("VT-DAU-BT", "LOT-DAU-1")
		again = factories.make_batch("VT-DAU-BT", "LOT-DAU-1")
		self.assertEqual(lot.name, again.name)
		self.assertEqual(frappe.db.count("Batch", {"batch_id": "LOT-DAU-1"}), 1)
