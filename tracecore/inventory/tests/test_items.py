from unittest.mock import patch

import frappe

from tracecore.inventory import items
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

# Item/Batch (ERPNext) kéo theo test record Company → Warehouse → Fiscal Year…, cần ERPNext đã chạy Setup Wizard;
# test này tự tạo dữ liệu qua factories nên bỏ phụ thuộc đó (site CI mới chưa có wizard).
test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]

OLD_GROUP_OPTIONS = "\nPackaging\nChemical Indicator\nLabel\nLubricant"
FR_GROUPS = (
	"Chemical Indicator",
	"Biological Indicator",
	"Test",
	"Packaging",
	"Pouch",
	"Filter Box",
	"Label",
	"Chemical",
	"Other",
)


def new_item(code, group=None, **fields):
	"""Item ERPNext chưa lưu, đủ trường bắt buộc."""
	factories.ensure_item_masters()
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": factories.ITEM_GROUP_ROOT,
			"stock_uom": factories.ITEM_UOM,
			"is_stock_item": 1,
			"tc_item_group_cssd": group,
			**fields,
		}
	)


class TestItemRules(IsolatedTestCase):
	def test_group_options_match_fr_m6_02_1(self):
		meta = frappe.get_meta("Item")
		options = meta.get_field("tc_item_group_cssd").options
		self.assertTrue(
			options.startswith(OLD_GROUP_OPTIONS), msg=options
		)  # bốn giá trị cũ giữ nguyên, đứng trước
		values = set(options.split("\n")) - {""}
		self.assertEqual(values, set(FR_GROUPS) | {"Lubricant", "Packaging Accessory"})  # + V1, A-97
		self.assertEqual(set(items.CSSD_GROUPS), values)
		self.assertEqual(len(items.CSSD_GROUPS), 11)
		self.assertEqual(meta.get_field("tc_ci_class").options, "\n1\n2\n3\n4\n5\n6")

	@bru("BRU-REP-011")
	def test_label_requires_compatible_method(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			new_item("F41-NHAN-1", "Label").insert(ignore_permissions=True)
		self.assertIn("Compatible Method", str(ctx.exception))
		item = new_item("F41-NHAN-1", "Label", tc_compatible_method="Plasma").insert(ignore_permissions=True)
		self.assertEqual(item.tc_compatible_method, "Plasma")

	@bru("BRU-REP-011")
	def test_label_codes_must_match_method(self):
		with self.assertRaises(frappe.ValidationError):
			new_item("VT-NHAN-HAP", "Label", tc_compatible_method="Plasma").insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			new_item("VT-NHAN-PLASMA", "Label", tc_compatible_method="Steam").insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):  # đúng mã nhưng sai nhóm
			new_item("VT-NHAN-HAP", "Packaging", tc_compatible_method="Steam").insert(ignore_permissions=True)
		steam = new_item("VT-NHAN-HAP", "Label", tc_compatible_method="Steam").insert(ignore_permissions=True)
		plasma = new_item("VT-NHAN-PLASMA", "Label", tc_compatible_method="Plasma").insert(
			ignore_permissions=True
		)
		self.assertEqual((steam.tc_compatible_method, plasma.tc_compatible_method), ("Steam", "Plasma"))
		self.assertEqual(items.LABEL_METHOD_BY_CODE, {"VT-NHAN-HAP": "Steam", "VT-NHAN-PLASMA": "Plasma"})

	def test_ci_class_only_for_chemical_indicator(self):
		with self.assertRaises(frappe.ValidationError):
			new_item("F41-PK-1", "Packaging", tc_ci_class="5").insert(ignore_permissions=True)
		ok = new_item("F41-CI-3", "Chemical Indicator", tc_ci_class="3").insert(ignore_permissions=True)
		self.assertEqual(ok.tc_ci_class, "3")  # V2: lớp 3 nhập được

	def test_invalid_group_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			new_item("F41-BAD-1", "Gauze").insert(ignore_permissions=True)

	@bru("BRU-INV-001")
	def test_expiry_groups_force_batch_and_expiry_flags(self):
		for index, group in enumerate(items.EXPIRY_REQUIRED_GROUPS):
			item = new_item(f"F41-EXP-{index}", group, has_batch_no=0, has_expiry_date=0).insert(
				ignore_permissions=True
			)
			self.assertEqual((item.has_batch_no, item.has_expiry_date), (1, 1), msg=group)
			self.assertTrue(items.requires_expiry(item.name), msg=group)
		self.assertEqual(
			set(items.EXPIRY_REQUIRED_GROUPS),
			{"Chemical Indicator", "Biological Indicator", "Chemical", "Lubricant"},
		)
		pouch = new_item("F41-POUCH-1", "Pouch", has_expiry_date=0).insert(ignore_permissions=True)
		self.assertEqual(pouch.has_expiry_date, 0)
		self.assertFalse(items.requires_expiry(pouch.name))
		flagged = new_item("F41-POUCH-2", "Pouch", has_expiry_date=1).insert(ignore_permissions=True)
		self.assertEqual((flagged.has_batch_no, flagged.has_expiry_date), (1, 1))
		self.assertTrue(items.requires_expiry(flagged.name))

	def test_average_valuation_forced(self):
		item = new_item("F41-AVG-1", "Test", valuation_method="FIFO").insert(ignore_permissions=True)
		self.assertEqual(item.valuation_method, "Moving Average")
		self.assertEqual(item.is_stock_item, 1)
		blank = new_item("F41-AVG-2", "Other", is_stock_item=0).insert(ignore_permissions=True)
		self.assertEqual((blank.is_stock_item, blank.valuation_method), (1, "Moving Average"))

	def test_existing_stock_with_other_valuation_is_blocked(self):
		item = new_item("F41-AVG-3", "Test").insert(ignore_permissions=True)
		item.valuation_method = "FIFO"
		with patch.object(items, "has_stock_ledger", return_value=True):
			with self.assertRaises(frappe.ValidationError) as ctx:
				item.save(ignore_permissions=True)
		self.assertIn("Moving Average", str(ctx.exception))

	def test_duplicate_code_blocked_case_and_whitespace(self):
		new_item("VT-X1", "Other").insert(ignore_permissions=True)
		with self.assertRaises(frappe.DuplicateEntryError) as ctx:
			new_item(" vt-x1 ", "Other").insert(ignore_permissions=True)
		self.assertIn("VT-X1", str(ctx.exception))
		with self.assertRaises(frappe.DuplicateEntryError):
			new_item("Vt-X1", "Other").insert(ignore_permissions=True)
		self.assertEqual(frappe.db.count("Item", {"item_code": ["like", "%X1%"]}), 1)

	def test_item_code_is_trimmed_on_insert(self):
		item = new_item("  F41-TRIM-1  ", "Other").insert(ignore_permissions=True)
		self.assertEqual((item.item_code, item.name), ("F41-TRIM-1", "F41-TRIM-1"))

	def test_reorder_levels_unique_warehouse_and_non_negative(self):
		wh1 = factories.make_warehouse("F41 Kho 1")
		wh2 = factories.make_warehouse("F41 Kho 2")

		def row(warehouse, level, request_type="Purchase"):
			return {
				"warehouse": warehouse,
				"warehouse_reorder_level": level,
				"warehouse_reorder_qty": 10,
				"material_request_type": request_type,
			}

		ok = new_item("F41-ROL-1", "Other", reorder_levels=[row(wh1, 5), row(wh2, 0)]).insert(
			ignore_permissions=True
		)
		self.assertEqual([d.warehouse for d in ok.reorder_levels], [wh1, wh2])
		with self.assertRaises(frappe.ValidationError) as dup:  # một kho một dòng (V4), dù khác loại yêu cầu
			new_item("F41-ROL-2", "Other", reorder_levels=[row(wh1, 5), row(wh1, 3, "Transfer")]).insert(
				ignore_permissions=True
			)
		self.assertIn("more than once", str(dup.exception))
		with self.assertRaises(frappe.ValidationError) as negative:
			new_item("F41-ROL-3", "Other", reorder_levels=[row(wh1, -1)]).insert(ignore_permissions=True)
		self.assertIn("cannot be negative", str(negative.exception))

	def test_reorder_level_defaults_to_purchase_request(self):
		wh = factories.make_warehouse("F41 Kho 3")
		item = new_item(
			"F41-ROL-4",
			"Other",
			reorder_levels=[{"warehouse": wh, "warehouse_reorder_level": 2, "warehouse_reorder_qty": 5}],
		).insert(ignore_permissions=True)
		self.assertEqual(item.reorder_levels[0].material_request_type, "Purchase")

	def test_reorder_level_rejects_group_warehouse(self):
		group = factories.make_warehouse("F41 Nhom", is_group=True)
		with self.assertRaises(frappe.ValidationError) as ctx:
			new_item(
				"F41-ROL-5",
				"Other",
				reorder_levels=[
					{"warehouse": group, "warehouse_reorder_level": 2, "warehouse_reorder_qty": 5}
				],
			).insert(ignore_permissions=True)
		self.assertIn("group warehouse", str(ctx.exception))

	def test_specification_saved(self):
		item = new_item("F41-SPEC-1", "Pouch", tc_specification="Box of 100 pouches 90 x 230 mm").insert(
			ignore_permissions=True
		)
		self.assertEqual(
			frappe.db.get_value("Item", item.name, "tc_specification"), "Box of 100 pouches 90 x 230 mm"
		)

	def test_legacy_item_without_batch_flag_still_saves(self):
		legacy = factories.make_item("F41-LEG-1", "Chemical Indicator", method="Steam", ci_class="5")
		self.assertEqual(frappe.db.get_value("Item", legacy.name, "has_batch_no"), 0)
		item = frappe.get_doc("Item", legacy.name)
		item.item_name = "F41-LEG-1 renamed"
		item.save(ignore_permissions=True)  # không lỗi
		self.assertEqual(
			frappe.db.get_value("Item", legacy.name, ["has_batch_no", "has_expiry_date", "valuation_method"]),
			(1, 1, "Moving Average"),
		)

	def test_item_without_cssd_group_untouched(self):
		item = new_item("F41-GEN-1", None, has_batch_no=0, valuation_method="FIFO").insert(
			ignore_permissions=True
		)
		self.assertEqual((item.has_batch_no, item.valuation_method), (0, "FIFO"))
		self.assertFalse(items.is_cssd_item(item.name))
		self.assertFalse(items.requires_expiry(item.name))

	def test_is_cssd_item(self):
		item = new_item("F41-CSSD-1", "Filter Box").insert(ignore_permissions=True)
		self.assertTrue(items.is_cssd_item(item.name))
		self.assertFalse(items.is_cssd_item("F41-NO-SUCH-ITEM"))
		self.assertFalse(items.requires_expiry("F41-NO-SUCH-ITEM"))
