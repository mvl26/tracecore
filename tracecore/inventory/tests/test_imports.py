"""Import vật tư (Item) từ Excel (FEAT-011 Task 7; FR-M9-11, FR-M6-01; A-41 Q3)."""

import uuid

import frappe

from tracecore.core import importer
from tracecore.core.tests.test_importer import workbook
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Warehouse", "Company", "Stock Entry Type", "Fiscal Year"]

HEADER = (
	"Item Code",
	"Item Name",
	"CSSD Group",
	"Unit",
	"Compatible Method",
	"Indicator Class",
	"Shelf Life (days)",
)


def item_code():
	return "IMP-VT-" + uuid.uuid4().hex[:6].upper()


class TestItemImport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		factories.ensure_item_masters()

	def run_rows(self, rows):
		return frappe.get_doc("Import Batch", importer.run("item", workbook(list(HEADER), rows), "f.xlsx"))

	def test_items_created_with_cssd_rules(self):
		code = item_code()
		batch = self.run_rows([[code, "Chỉ thị loại 5 hấp", "Chemical Indicator", "Nos", "Steam", "5", None]])
		self.assertEqual(batch.created, 1, batch.rows)
		item = frappe.get_doc("Item", code)
		self.assertEqual(
			(item.tc_item_group_cssd, item.tc_compatible_method, item.tc_ci_class),
			("Chemical Indicator", "Steam", "5"),
		)
		self.assertEqual((item.has_batch_no, item.has_expiry_date), (1, 1))  # luật FEAT-041 tự bật lô/hạn

	def test_rule_violation_is_row_error_not_crash(self):
		code = item_code()
		batch = self.run_rows([[code, "Nhãn không phương pháp", "Label", "Nos", None, None, None]])
		self.assertEqual((batch.created, batch.failed), (0, 1))
		self.assertFalse(frappe.db.exists("Item", code))

	def test_existing_item_skipped(self):
		code = factories.make_item(item_code(), "Chemical").name
		self.assertEqual(self.run_rows([[code, "Đã có", "Chemical", "Nos", None, None, None]]).skipped, 1)

	def test_unknown_unit_is_row_error(self):
		result = importer.check(
			"item", workbook(list(HEADER), [[item_code(), "X", "Chemical", "Thùng lạ", None, None, None]])
		)
		self.assertEqual([i["code"] for i in result["issues"]], ["UOM_NOT_FOUND"])
