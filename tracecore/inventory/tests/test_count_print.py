"""Phiếu kiểm kê in được: Print Format "TC Stock Count Sheet" (FEAT-043; FR-M6-05; UC-26; A-52 C13)."""

import frappe

from tracecore.inventory.tests.test_consume import ITEM
from tracecore.inventory.tests.test_count import CountCase
from tracecore.ui import stock_count_print

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Stock Reconciliation",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]

DOCTYPE = "Stock Reconciliation"
FORMAT = stock_count_print.SHEET_FORMAT


class TestStockCountSheet(CountCase):
	def sheet(self, **kwargs):
		return self.count([self.row(self.near, 4, reason="Hỏng 1 chai"), self.row(self.far, 9)], **kwargs)

	def test_format_is_installed_for_the_doctype(self):
		self.assertEqual(frappe.db.get_value("Print Format", FORMAT, "doc_type"), DOCTYPE)

	def test_sheet_lists_every_lot_with_system_counted_and_difference(self):  # FR-M6-05
		doc = self.sheet()
		html = frappe.get_print(DOCTYPE, doc.name, FORMAT)
		for text in (doc.name, ITEM, self.near, self.far, "Hỏng 1 chai", "-1", "10"):
			self.assertIn(text, html)

	def test_context_rows_carry_the_difference_and_the_expiry(self):
		context = stock_count_print.tc_stock_count_context(self.sheet().name)
		rows = {row["batch"]: row for row in context["items"]}
		self.assertEqual(
			(rows[self.near]["system"], rows[self.near]["counted"], rows[self.near]["difference"]),
			("5", "4", "-1"),
		)
		self.assertEqual(rows[self.far]["difference"], "-1")
		self.assertRegex(rows[self.near]["expiry"], r"^\d{2}/\d{2}/\d{4}$")
		self.assertEqual(context["warehouses"], [self.warehouse])

	def test_a_draft_is_marked_as_not_approved(self):
		context = stock_count_print.tc_stock_count_context(self.sheet().name)
		self.assertTrue(context["draft"])
		self.assertFalse(context["cancelled"])

	def test_a_posted_sheet_is_not_marked_as_draft(self):
		doc = self.sheet()
		doc.submit()
		self.assertFalse(stock_count_print.tc_stock_count_context(doc.name)["draft"])

	def test_every_value_is_escaped(self):
		doc = self.count([self.row(self.far, 8, reason="<script>alert(1)</script>")])
		html = frappe.get_print(DOCTYPE, doc.name, FORMAT)
		self.assertNotIn("<script>alert(1)", html)

	def test_only_a_reader_can_print(self):
		doc = self.sheet()
		frappe.set_user(self.user("TC R08"))
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			stock_count_print.tc_stock_count_context(doc.name)
