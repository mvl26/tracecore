import frappe
from frappe.utils import add_days, today

from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

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


def audit_rows(doctype, name, action=None):
	filters = {"ref_doctype": doctype, "ref_name": name}
	if action:
		filters["action"] = action
	return frappe.get_all(
		"Audit Log", filters=filters, fields=["name", "action", "new_value", "old_value", "user"]
	)


class TestInventoryAudit(IsolatedTestCase):
	def test_item_create_and_update_logged(self):
		item = factories.make_item("VT-AUD-1", "Packaging")
		self.assertEqual(len(audit_rows("Item", "VT-AUD-1", "Create")), 1)
		item.item_name = "Vat tu kiem toan"
		item.save(ignore_permissions=True)
		updates = audit_rows("Item", "VT-AUD-1", "Update")
		self.assertEqual(len(updates), 1)
		self.assertIn("item_name", updates[0].new_value)

	def test_batch_create_logged(self):
		factories.make_item("VT-AUD-2", "Chemical Indicator")
		factories.make_batch("VT-AUD-2", "LOT-AUD-2", "2099-01-31")
		self.assertEqual(len(audit_rows("Batch", "LOT-AUD-2", "Create")), 1)

	def test_non_cssd_item_not_logged(self):
		factories.ensure_item_masters()
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "VT-AUD-GENERIC",
				"item_name": "Generic",
				"item_group": factories.ITEM_GROUP_ROOT,
				"stock_uom": factories.ITEM_UOM,
				"is_stock_item": 1,
				"has_batch_no": 1,
			}
		).insert(ignore_permissions=True)
		batch = frappe.get_doc({"doctype": "Batch", "batch_id": "LOT-AUD-GENERIC", "item": item.name}).insert(
			ignore_permissions=True
		)
		item.item_name = "Generic 2"
		item.save(ignore_permissions=True)
		self.assertEqual(audit_rows("Item", item.name), [])
		self.assertEqual(audit_rows("Batch", batch.name), [])


class TestStockEntryAudit(IsolatedTestCase):
	def _receipt(self, item_code, batch_id, submit=True):
		factories.make_item(item_code, "Chemical", apply_rules=True)
		supplier = factories.make_supplier("F41 NCC Audit")
		line = {
			"item_code": item_code,
			"batch_id": batch_id,
			"expiry_date": add_days(today(), 200),
			"qty": 3,
			"rate": 1000,
		}
		return factories.make_receipt([line], supplier, "PGH-AUD", submit=submit)

	def test_stock_entry_submit_and_cancel_logged(self):
		entry = self._receipt("VT-AUD-SE1", "LOT-AUD-SE1")
		self.assertEqual(len(audit_rows("Stock Entry", entry.name, "Create")), 1)
		self.assertEqual(len(audit_rows("Stock Entry", entry.name, "Submit")), 1)
		entry.cancel()
		self.assertEqual(len(audit_rows("Stock Entry", entry.name, "Cancel")), 1)

	def test_non_cssd_stock_entry_not_logged(self):
		factories.ensure_item_masters()
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "VT-AUD-SE-GENERIC",
				"item_name": "Generic",
				"item_group": factories.ITEM_GROUP_ROOT,
				"stock_uom": factories.ITEM_UOM,
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		entry = factories.make_receipt([{"item_code": "VT-AUD-SE-GENERIC", "qty": 2, "rate": 5}], None, None)
		self.assertEqual(audit_rows("Stock Entry", entry.name), [])
