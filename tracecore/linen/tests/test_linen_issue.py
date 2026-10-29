"""Linen Issue (FEAT-035; FR-M3-05, .1, .2, FR-M3-06.2; BRU-LIN-001; A-50 G2, G4, G5, G8)."""

import frappe

from tracecore.tests.factories import (
	linen_line,
	make_department,
	make_linen_collection,
	make_linen_issue,
	make_linen_type,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Linen Issue"


class TestLinenIssue(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.sheet = make_linen_type(std_weight_kg=0.5).name

	@bru("BRU-LIN-001")
	def test_issue_is_saved_with_totals_and_name_series(self):  # FR-M3-05
		doc = make_linen_issue([linen_line(self.sheet, 10, 5)], submit=True)
		self.assertRegex(doc.name, r"^LNI-\d{4}-\d{5}$")
		self.assertEqual((doc.total_qty, doc.total_weight_kg, doc.docstatus), (10, 5, 1))
		self.assertTrue(doc.issued_at)
		self.assertTrue(doc.recipient_name)

	@bru("BRU-LIN-001")
	def test_missing_pieces_are_converted_from_kg(self):  # FR-M3-01.3 dùng chung
		doc = make_linen_issue([{"linen_type": self.sheet, "weight_kg": 5}])
		row = doc.lines[0]
		self.assertEqual((row.qty, row.weight_source), (10, "Converted"))

	def test_line_over_tolerance_needs_a_note(self):
		with self.assertRaises(frappe.ValidationError):
			make_linen_issue([linen_line(self.sheet, 10, 8)])
		doc = make_linen_issue([linen_line(self.sheet, 10, 8, variance_note="Ướt")])
		self.assertEqual(doc.lines[0].variance_note, "Ướt")

	def test_issue_without_lines_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_linen_issue([])

	def test_inactive_type_cannot_be_issued_but_can_be_disposed(self):
		old = make_linen_type(std_weight_kg=0.5, is_active=0).name
		with self.assertRaises(frappe.ValidationError):
			make_linen_issue([linen_line(old, 2, 1)])
		self.assertEqual(make_linen_issue([linen_line(old, 2, 1)], kind="Dispose").kind, "Dispose")

	def test_submit_needs_the_recipient_signature(self):  # FR-M3-05.1
		with self.assertRaises(frappe.ValidationError):
			make_linen_issue([linen_line(self.sheet)], recipient=None, submit=True)
		with self.assertRaises(frappe.ValidationError):
			make_linen_issue([linen_line(self.sheet)], sign_method=None, submit=True)
		with self.assertRaises(frappe.ValidationError):  # Touch mà chưa vẽ chữ ký
			make_linen_issue([linen_line(self.sheet)], sign_method="Touch", submit=True)
		doc = make_linen_issue(
			[linen_line(self.sheet)],
			sign_method="Touch",
			signature="data:image/png;base64,AAAA",
			submit=True,
		)
		self.assertTrue(doc.signed_at)

	def test_new_stock_is_an_issue_too(self):  # UC-18 A1
		doc = make_linen_issue([linen_line(self.sheet, 4, 2)], kind="New", submit=True)
		self.assertEqual(doc.kind, "New")

	def test_dispose_needs_reason_and_photo(self):  # FR-M3-06.2
		with self.assertRaises(frappe.ValidationError):
			make_linen_issue([linen_line(self.sheet)], kind="Dispose", reason="")
		with self.assertRaises(frappe.ValidationError):
			make_linen_issue([linen_line(self.sheet)], kind="Dispose", evidence=None)
		doc = make_linen_issue([linen_line(self.sheet)], kind="Dispose", submit=True)
		self.assertFalse(doc.recipient or doc.sign_method or doc.signature)

	def test_kind_must_be_known(self):
		with self.assertRaises(frappe.ValidationError):
			make_linen_issue([linen_line(self.sheet)], kind="Gift")

	@bru("BRU-LIN-004")
	def test_over_max_quota_warns_but_does_not_block(self):  # FR-M3-05.2
		department = make_department("Test linen quota ward")
		kind = make_linen_type(
			std_weight_kg=0.5, quotas=[{"department": department, "min_qty": 5, "max_qty": 12}]
		).name
		make_linen_issue([linen_line(kind, 10, 5)], department=department, submit=True)
		doc = make_linen_issue([linen_line(kind, 5, 2.5)], department=department)
		self.assertIn(kind, doc.quota_warning)
		self.assertEqual(doc.docstatus, 0)  # vẫn lưu được

	def test_department_without_quota_is_allowed(self):  # UC-18 E1
		doc = make_linen_issue([linen_line(self.sheet, 99, 49.5)])
		self.assertFalse(doc.quota_warning)

	def test_signed_issue_is_amended_not_overwritten(self):  # UC-18 E3, G8
		doc = make_linen_issue([linen_line(self.sheet, 10, 5)], submit=True)
		doc.cancel()
		amended = frappe.copy_doc(doc)
		amended.docstatus = 0
		amended.amended_from = doc.name
		amended.lines[0].qty = 9
		amended.lines[0].weight_kg = 4.5
		amended.insert()
		amended.submit()
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 2)
		self.assertTrue(amended.name.startswith(doc.name + "-"))

	def test_issue_cannot_be_deleted(self):
		doc = make_linen_issue([linen_line(self.sheet)], submit=True)
		doc.cancel()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(DOCTYPE, doc.name)

	def test_collection_factory_still_works(self):  # dùng chung normalize_line
		self.assertEqual(make_linen_collection(submit=True).docstatus, 1)
