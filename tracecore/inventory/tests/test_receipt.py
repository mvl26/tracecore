from datetime import date
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.inventory import receipt
from tracecore.inventory.receipt import ReceiptInvalid, ReceiptLine
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

# Item/Batch/Stock Entry (ERPNext) kéo theo test record Company, Warehouse, Fiscal Year…, cần Setup Wizard;
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

TOMORROW = add_days(today(), 1)
YESTERDAY = add_days(today(), -1)
FAR = add_days(today(), 400)


def cssd_item(code, group="Chemical", has_expiry_date=None):
	"""Item vật tư như người dùng nhập trên Desk (luật FEAT-041 áp đủ)."""
	item = factories.make_item(code, group, apply_rules=True)
	if has_expiry_date is not None and item.has_expiry_date != has_expiry_date:
		item.has_expiry_date = has_expiry_date
		item.save(ignore_permissions=True)
	return item


def line(item_code, batch_id, expiry=None, qty=10, rate=100000):
	return {"item_code": item_code, "batch_id": batch_id, "expiry_date": expiry, "qty": qty, "rate": rate}


def codes(exc_or_issues):
	issues = getattr(exc_or_issues, "issues", exc_or_issues)
	return sorted(issue.code for issue in issues)


def bin_values(item_code, warehouse):
	return frappe.db.get_value(
		"Bin",
		{"item_code": item_code, "warehouse": warehouse},
		["actual_qty", "valuation_rate"],
		as_dict=True,
	)


class ReceiptCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.masters = factories.ensure_stock_masters()
		self.warehouse = self.masters["warehouse"]
		self.supplier = factories.make_supplier("F41 NCC A")

	def receipt(self, lines, **kwargs):
		kwargs.setdefault("supplier", self.supplier)
		kwargs.setdefault("document_no", "PGH-001")
		return factories.make_receipt(lines, **kwargs)

	def assertBlocked(self, lines, expected_codes, **kwargs):
		with self.assertRaises(ReceiptInvalid) as ctx:
			self.receipt(lines, **kwargs)
		self.assertEqual(codes(ctx.exception), sorted(expected_codes))
		return ctx.exception


class TestReceiptPosting(ReceiptCase):
	@bru("BRU-INV-001")
	def test_receipt_posts_stock_entry_and_updates_batch_stock(self):
		cssd_item("F41-R-1")
		entry = self.receipt([line("F41-R-1", "LOT-R1", FAR, qty=12)])
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(entry.purpose, "Material Receipt")
		self.assertEqual(frappe.db.get_value("Batch", "LOT-R1", "batch_qty"), 12)
		self.assertEqual(bin_values("F41-R-1", self.warehouse).actual_qty, 12)
		self.assertEqual(getdate(frappe.db.get_value("Batch", "LOT-R1", "expiry_date")), getdate(FAR))

	def test_weighted_average_across_two_receipts(self):
		cssd_item("F41-R-2")
		self.receipt([line("F41-R-2", "LOT-R2A", FAR, qty=10, rate=100000)], document_no="PGH-A")
		second = self.receipt([line("F41-R-2", "LOT-R2B", FAR, qty=10, rate=200000)], document_no="PGH-B")
		self.assertEqual(bin_values("F41-R-2", self.warehouse).valuation_rate, 150000)
		sle_rate = frappe.db.get_value(
			"Stock Ledger Entry", {"voucher_no": second.name, "is_cancelled": 0}, "valuation_rate"
		)
		self.assertEqual(sle_rate, 150000)

	def test_same_lot_two_receipts_adds_to_one_batch(self):
		cssd_item("F41-R-3")
		self.receipt([line("F41-R-3", "LOT-R3", FAR, qty=5)], document_no="PGH-1")
		self.receipt([line("F41-R-3", "LOT-R3", FAR, qty=7)], document_no="PGH-2")
		self.assertEqual(frappe.db.count("Batch", {"item": "F41-R-3"}), 1)
		self.assertEqual(frappe.db.get_value("Batch", "LOT-R3", "batch_qty"), 12)

	def test_batch_created_only_on_submit(self):
		cssd_item("F41-R-4")
		draft = self.receipt([line("F41-R-4", "LOT-R4", FAR)], submit=False)
		self.assertEqual(draft.docstatus, 0)
		self.assertFalse(frappe.db.exists("Batch", "LOT-R4"))
		draft.submit()
		self.assertTrue(frappe.db.exists("Batch", "LOT-R4"))
		self.assertEqual(frappe.db.get_value("Batch", "LOT-R4", "batch_qty"), 10)
		# lưu nháp lỗi hạn vẫn bị chặn sớm, chưa tạo lô
		with self.assertRaises(ReceiptInvalid):
			self.receipt([line("F41-R-4", "LOT-R4-OLD", YESTERDAY)], submit=False, document_no="PGH-X")
		self.assertFalse(frappe.db.exists("Batch", "LOT-R4-OLD"))

	def test_batch_supplier_and_non_batchwise_valuation(self):
		cssd_item("F41-R-5")
		self.receipt([line("F41-R-5", "LOT-R5", FAR)])
		batch = frappe.db.get_value("Batch", "LOT-R5", ["supplier", "use_batchwise_valuation"], as_dict=True)
		self.assertEqual(batch.supplier, self.supplier)
		self.assertEqual(batch.use_batchwise_valuation, 0)

	def test_cancel_receipt_reverses_stock(self):
		cssd_item("F41-R-6")
		entry = self.receipt([line("F41-R-6", "LOT-R6", FAR, qty=9)])
		self.assertEqual(frappe.db.get_value("Batch", "LOT-R6", "batch_qty"), 9)
		entry.cancel()
		self.assertEqual(frappe.db.get_value("Batch", "LOT-R6", "batch_qty"), 0)
		self.assertEqual(bin_values("F41-R-6", self.warehouse).actual_qty, 0)

	@bru("BRU-INV-001")
	def test_non_average_item_blocked_when_stock_exists(self):
		item = cssd_item("F41-R-7")
		self.receipt([line("F41-R-7", "LOT-R7", FAR)])
		frappe.db.set_value("Item", item.name, "valuation_method", "FIFO")
		item = frappe.get_doc("Item", item.name)
		with self.assertRaises(frappe.ValidationError) as ctx:
			item.save(ignore_permissions=True)
		self.assertIn("Moving Average", str(ctx.exception))

	def test_zero_rate_warns_but_posts(self):
		cssd_item("F41-R-8")
		entry = self.receipt([line("F41-R-8", "LOT-R8", FAR, rate=0)])
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(entry.items[0].allow_zero_valuation_rate, 1)
		messages = [m for m in frappe.get_message_log() if "0" in str(m.get("message"))]
		self.assertTrue(any(m.get("indicator") == "orange" for m in messages), msg=messages)


class TestReceiptRules(ReceiptCase):
	@bru("BRU-INV-001")
	def test_expired_lot_blocked(self):
		cssd_item("F41-E-1")
		self.assertBlocked([line("F41-E-1", "LOT-E1", YESTERDAY)], ["EXPIRY_PAST"])
		self.assertFalse(frappe.db.exists("Batch", "LOT-E1"))
		self.assertFalse(frappe.db.exists("Stock Entry", {"tc_document_no": "PGH-001"}))

	def test_expiry_today_accepted(self):
		cssd_item("F41-E-2")
		entry = self.receipt([line("F41-E-2", "LOT-E2", today())])
		self.assertEqual(entry.docstatus, 1)

	@bru("BRU-INV-001")
	def test_indicator_biological_chemical_without_expiry_blocked(self):
		for index, group in enumerate(
			("Chemical Indicator", "Biological Indicator", "Chemical", "Lubricant")
		):
			code = f"F41-E-3-{index}"
			cssd_item(code, group)
			self.assertBlocked([line(code, f"LOT-E3-{index}", None)], ["EXPIRY_REQUIRED"])
			self.assertFalse(frappe.db.exists("Stock Entry", {"tc_document_no": "PGH-001"}), msg=group)

	def test_flagged_item_requires_expiry_even_if_group_optional(self):
		cssd_item("F41-E-4", "Pouch", has_expiry_date=1)
		self.assertBlocked([line("F41-E-4", "LOT-E4", None)], ["EXPIRY_REQUIRED"])
		cssd_item("F41-E-4B", "Pouch", has_expiry_date=0)
		entry = self.receipt([line("F41-E-4B", "LOT-E4B", None)])
		self.assertEqual(entry.docstatus, 1)

	def test_expiry_given_for_untracked_item_blocked(self):
		cssd_item("F41-E-5", "Pouch", has_expiry_date=0)
		self.assertBlocked([line("F41-E-5", "LOT-E5", FAR)], ["EXPIRY_NOT_TRACKED"])

	def test_missing_batch_blocked(self):
		cssd_item("F41-E-6")
		self.assertBlocked([line("F41-E-6", "  ", FAR)], ["BATCH_REQUIRED"])

	def test_qty_zero_or_negative_blocked(self):
		cssd_item("F41-E-7")
		for qty in (0, -3):
			issues = receipt.check_lines(
				[ReceiptLine(1, "F41-E-7", "LOT-E7", getdate(FAR), qty, 1)], getdate()
			)
			self.assertEqual(codes(issues), ["QTY_INVALID"], msg=qty)
		# qua form: ERPNext hoặc luật nhập kho đều chặn, không ghi sổ
		with self.assertRaises(frappe.ValidationError):
			self.receipt([line("F41-E-7", "LOT-E7", FAR, qty=0)])
		self.assertFalse(frappe.db.exists("Batch", "LOT-E7"))

	def test_negative_rate_blocked(self):
		cssd_item("F41-E-8")
		self.assertBlocked([line("F41-E-8", "LOT-E8", FAR, rate=-1)], ["RATE_NEGATIVE"])

	def test_missing_supplier_or_document_no_blocked(self):
		cssd_item("F41-E-9")
		with self.assertRaises(ReceiptInvalid) as ctx:
			factories.make_receipt([line("F41-E-9", "LOT-E9", FAR)], supplier=None, document_no="")
		self.assertEqual(codes(ctx.exception), ["DOCUMENT_REQUIRED", "SUPPLIER_REQUIRED"])

	def test_same_lot_different_expiry_blocked(self):
		cssd_item("F41-L-1")
		self.receipt([line("F41-L-1", "LOT-L1", FAR)], document_no="PGH-1")
		self.assertBlocked(
			[line("F41-L-1", "LOT-L1", add_days(FAR, 30))], ["BATCH_EXPIRY_MISMATCH"], document_no="PGH-2"
		)

	def test_batch_of_other_item_blocked(self):
		cssd_item("F41-L-2A")
		cssd_item("F41-L-2B")
		self.receipt([line("F41-L-2A", "LOT-L2", FAR)], document_no="PGH-1")
		self.assertBlocked([line("F41-L-2B", "LOT-L2", FAR)], ["BATCH_ITEM_MISMATCH"], document_no="PGH-2")

	def test_conflicting_lot_inside_one_document_blocked(self):
		cssd_item("F41-L-3")
		self.assertBlocked(
			[line("F41-L-3", "LOT-L3", FAR), line("F41-L-3", "LOT-L3", add_days(FAR, 5))],
			["LOT_CONFLICT_IN_DOCUMENT"],
		)

	def test_same_lot_twice_with_same_expiry_in_one_document_accepted(self):
		cssd_item("F41-L-4")
		entry = self.receipt([line("F41-L-4", "LOT-L4", FAR, qty=3), line("F41-L-4", "LOT-L4", FAR, qty=4)])
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Batch", "LOT-L4", "batch_qty"), 7)

	def test_all_errors_listed_at_once(self):
		cssd_item("F41-A-1")
		cssd_item("F41-A-2", "Pouch", has_expiry_date=0)
		exc = self.assertBlocked(
			[
				line("F41-A-1", "LOT-A1", YESTERDAY),
				line("F41-A-1", "LOT-A1B", None),
				line("F41-A-2", "", FAR, qty=0),
			],
			["BATCH_REQUIRED", "EXPIRY_NOT_TRACKED", "EXPIRY_PAST", "EXPIRY_REQUIRED", "QTY_INVALID"],
		)
		self.assertEqual({issue.row for issue in exc.issues}, {1, 2, 3})
		message = " ".join(str(m.get("message")) for m in frappe.get_message_log())
		for row in (1, 2, 3):
			self.assertIn(f"Line {row}:", message)  # mọi dòng lỗi nằm trong cùng một thông báo

	def test_non_cssd_stock_entry_untouched(self):
		factories.ensure_item_masters()
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "F41-GENERIC",
				"item_name": "Generic",
				"item_group": factories.ITEM_GROUP_ROOT,
				"stock_uom": factories.ITEM_UOM,
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		entry = self.receipt(
			[{"item_code": "F41-GENERIC", "batch_id": None, "expiry_date": None, "qty": 4, "rate": 0}],
			supplier=None,
			document_no="",
		)
		self.assertEqual(entry.docstatus, 1)

	def test_issue_purpose_untouched(self):
		cssd_item("F41-I-1")
		self.receipt([line("F41-I-1", "LOT-I1", FAR, qty=10)])
		if not frappe.db.exists("Stock Entry Type", "Material Issue"):
			frappe.get_doc(
				{"doctype": "Stock Entry Type", "name": "Material Issue", "purpose": "Material Issue"}
			).insert(ignore_permissions=True)
		issue = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Issue",
				"purpose": "Material Issue",
				"company": self.masters["company"],
				"from_warehouse": self.warehouse,
				"items": [
					{
						"item_code": "F41-I-1",
						"qty": 2,
						"uom": factories.ITEM_UOM,
						"stock_uom": factories.ITEM_UOM,
						"conversion_factor": 1,
						"s_warehouse": self.warehouse,
						"batch_no": "LOT-I1",
						"use_serial_batch_fields": 1,
					}
				],
			}
		)
		issue.insert(ignore_permissions=True)
		issue.submit()
		self.assertEqual(issue.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Batch", "LOT-I1", "batch_qty"), 8)

	def test_check_lines_is_pure(self):
		cssd_item("F41-P-1")
		before = (frappe.db.count("Batch"), frappe.db.count("Stock Entry"))
		issues = receipt.check_lines(
			[
				ReceiptLine(1, "F41-P-1", "LOT-P1", getdate(FAR), 5, 100),
				ReceiptLine(2, "NOPE", "L", None, 1, 1),
			],
			getdate(),
		)
		self.assertEqual(codes(issues), ["ITEM_NOT_FOUND"])
		self.assertEqual((frappe.db.count("Batch"), frappe.db.count("Stock Entry")), before)

	def test_check_lines_codes_for_item_problems(self):
		cssd_item("F41-P-2")
		frappe.db.set_value("Item", "F41-P-2", "disabled", 1)
		factories.make_item("F41-P-3", "Pouch", has_batch_no=0)  # Item cũ: chưa bật theo dõi lô
		generic = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "F41-P-4",
				"item_name": "Generic",
				"item_group": factories.ITEM_GROUP_ROOT,
				"stock_uom": factories.ITEM_UOM,
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		issues = receipt.check_lines(
			[
				ReceiptLine(1, "F41-P-2", "L1", None, 1, 1),
				ReceiptLine(2, "F41-P-3", "L2", None, 1, 1),
				ReceiptLine(3, generic.name, "L3", None, 1, 1),
			],
			getdate(),
		)
		self.assertEqual(codes(issues), ["ITEM_DISABLED", "ITEM_NOT_BATCHED", "ITEM_NOT_CSSD"])

	def test_header_codes(self):
		self.assertEqual(
			codes(receipt.check_header(None, " ", "")),
			["DOCUMENT_REQUIRED", "SUPPLIER_REQUIRED", "WAREHOUSE_REQUIRED"],
		)
		self.assertEqual(receipt.check_header("S", "D", "W"), [])

	def test_zero_rate_rows_only_valid_quantity(self):
		lines = [
			ReceiptLine(1, "A", "L", None, 5, 0),
			ReceiptLine(2, "A", "L", None, 5, 10),
			ReceiptLine(3, "A", "L", None, 0, 0),
		]
		self.assertEqual(receipt.zero_rate_rows(lines), [1])

	def test_batch_id_longer_than_140_blocked(self):
		cssd_item("F41-B-1")
		self.assertBlocked([line("F41-B-1", "X" * 141, FAR)], ["BATCH_ID_INVALID"])

	def test_batch_id_is_trimmed(self):
		cssd_item("F41-B-2")
		self.receipt([line("F41-B-2", "  LOT-B2  ", FAR)])
		self.assertTrue(frappe.db.exists("Batch", "LOT-B2"))

	def test_company_missing_message(self):
		cssd_item("F41-C-1")
		doc = factories.build_receipt([line("F41-C-1", "LOT-C1", FAR)], self.supplier, "PGH-C")
		doc.company = None
		with patch("erpnext.get_default_company", return_value=None):
			with self.assertRaises(frappe.ValidationError) as ctx:
				receipt.prepare_receipt(doc)
		self.assertNotIn("Traceback", str(ctx.exception))
		self.assertNotIsInstance(ctx.exception, (AttributeError, TypeError))

	def test_today_vn_uses_system_timezone(self):
		self.assertIsInstance(receipt.today_vn(), date)
		self.assertEqual(receipt.today_vn(), getdate(today()))


class TestReceiptAsRole(ReceiptCase):
	def _post_as(self, role, item_code, batch_id):
		user = factories.make_user(f"f41-{role.replace(chr(32), chr(45)).lower()}@example.com", [role])
		doc = factories.build_receipt([line(item_code, batch_id, FAR)], self.supplier, "PGH-ROLE")
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		doc.insert()
		doc.submit()
		return doc

	def test_r09_and_r06_can_post_receipt_without_ignore_permissions(self):
		cssd_item("F41-U-1")
		cssd_item("F41-U-2")
		first = self._post_as("TC R09", "F41-U-1", "LOT-U1")
		first.cancel()  # R09 hủy sổ bằng quyền của mình (kể cả Serial and Batch Bundle)
		self.assertEqual(first.docstatus, 2)
		frappe.set_user("Administrator")
		second = self._post_as("TC R06", "F41-U-2", "LOT-U2")
		self.assertEqual((first.docstatus, second.docstatus), (2, 1))
		self.assertEqual(frappe.db.get_value("Batch", "LOT-U2", "batch_qty"), 10)
