"""Biên nhận thu gom đồ vải: Print Format "TC Linen Receipt" (FEAT-033; FR-M3-01.5; A-49 L7)."""

import frappe

from tracecore.tests.factories import linen_line, make_linen_collection, make_linen_type, make_user
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.ui import linen_print

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Linen Collection"


class TestLinenReceipt(IsolatedTestCase):
	def collection(self, **kwargs):
		sheet = make_linen_type("Săng mổ", std_weight_kg=0.5).name
		gown = make_linen_type("Áo choàng", std_weight_kg=1.0).name
		return make_linen_collection(
			lines=[linen_line(sheet, 10, 5.5, contaminated=1), linen_line(gown, 3, 3, contaminated=0)],
			submit=True,
			**kwargs,
		)

	def test_format_is_installed_for_the_doctype(self):
		self.assertEqual(frappe.db.get_value("Print Format", linen_print.RECEIPT_FORMAT, "doc_type"), DOCTYPE)

	@bru("BRU-LIN-001")
	def test_receipt_shows_the_collection_and_totals(self):  # FR-M3-01.5
		doc = self.collection(delivered_by="Nguyễn Văn Hộ Lý")
		html = frappe.get_print(DOCTYPE, doc.name, linen_print.RECEIPT_FORMAT)
		for text in (doc.name, "Nguyễn Văn Hộ Lý", "Săng mổ", "Áo choàng", "5,5", "13"):
			self.assertIn(text, html)

	def test_every_value_is_escaped(self):
		doc = self.collection(delivered_by="<script>alert(1)</script>", note="<b>ghi chú</b>")
		html = frappe.get_print(DOCTYPE, doc.name, linen_print.RECEIPT_FORMAT)
		self.assertNotIn("<script>alert(1)", html)
		self.assertNotIn("<b>ghi chú</b>", html)
		self.assertIn(
			"lt;script", html
		)  # Frappe đã mã hóa Data khi lưu; |e mã hóa tiếp, không bao giờ ra thẻ thật
		self.assertIn("&lt;b&gt;ghi chú", html)

	def test_draft_is_marked_not_recorded(self):
		doc = make_linen_collection()
		self.assertTrue(linen_print.tc_linen_receipt_context(doc.name)["draft"])

	def test_context_formats_weights_with_a_decimal_comma(self):
		context = linen_print.tc_linen_receipt_context(self.collection().name)
		self.assertEqual(context["total_weight"], "8,5")
		self.assertEqual([row["weight"] for row in context["items"]], ["5,5", "3"])
		self.assertEqual([row["contaminated"] for row in context["items"]], [1, 0])

	def test_kg_helper(self):
		self.assertEqual(linen_print.kg(12.5), "12,5")
		self.assertEqual(linen_print.kg(3), "3")
		self.assertEqual(linen_print.kg(0.1234), "0,123")
		self.assertEqual(linen_print.kg(None), "0")

	def test_user_without_read_access_cannot_print(self):
		doc = self.collection()
		frappe.set_user(make_user("linen-print-r08@example.com", roles=("TC R08",)))
		with self.assertRaises(frappe.PermissionError):
			linen_print.tc_linen_receipt_context(doc.name)
