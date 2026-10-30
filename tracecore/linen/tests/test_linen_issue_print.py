"""Biên nhận cấp phát đồ vải: Print Format "TC Linen Issue Receipt" (FEAT-035; FR-M3-05.1; A-50 G9)."""

import frappe

from tracecore.tests.factories import linen_line, make_linen_issue, make_linen_type
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.ui import linen_print

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Linen Issue"
FORMAT = "TC Linen Issue Receipt"


class TestLinenIssueReceipt(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.sheet = make_linen_type("Săng cấp", std_weight_kg=0.5).name

	def test_format_is_installed_for_the_doctype(self):
		self.assertEqual(frappe.db.get_value("Print Format", FORMAT, "doc_type"), DOCTYPE)

	@bru("BRU-LIN-001")
	def test_receipt_shows_lines_totals_and_card_signature(self):  # FR-M3-05.1
		doc = make_linen_issue([linen_line(self.sheet, 10, 5.5)], submit=True)
		html = frappe.get_print(DOCTYPE, doc.name, FORMAT)
		for text in (doc.name, "Săng cấp", "5,5", "10", doc.recipient_name):
			self.assertIn(text, html)

	def test_touch_signature_is_printed_as_an_image(self):
		doc = make_linen_issue(
			[linen_line(self.sheet)],
			sign_method="Touch",
			signature="data:image/png;base64,AAAA",
			submit=True,
		)
		self.assertIn("<img", frappe.get_print(DOCTYPE, doc.name, FORMAT))

	def test_dispose_receipt_shows_the_reason(self):
		doc = make_linen_issue(
			[linen_line(self.sheet)], kind="Dispose", reason="Rách <b>nặng</b>", submit=True
		)
		html = frappe.get_print(DOCTYPE, doc.name, FORMAT)
		self.assertIn("Rách", html)
		self.assertNotIn("<b>nặng</b>", html)

	def test_draft_is_marked_not_recorded(self):
		doc = make_linen_issue([linen_line(self.sheet)])
		self.assertTrue(linen_print.tc_linen_issue_context(doc.name)["draft"])
