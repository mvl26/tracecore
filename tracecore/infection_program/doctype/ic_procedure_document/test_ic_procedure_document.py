"""IC Procedure Document — sổ văn bản nội bộ (FEAT-058 AC-8..AC-10; FR-M11-07, FR-M11-07.1, .2; BRU-ICP-005)."""

import frappe
from frappe.utils import add_days, add_months, getdate, today

from tracecore.core import indicators
from tracecore.infection_program import procedure_documents
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

DOCTYPE = "IC Procedure Document"


class TestICProcedureDocument(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.sql("delete from `tabIC Procedure Document`")

	def test_meta_and_permissions(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertFalse(meta.is_submittable)
		self.assertEqual(
			meta.get_field("status").options.split("\n"),
			["Effective", "Review Needed", "Superseded", "Draft", "Withdrawn"],  # FEAT-073 (A-151 Q3)
		)
		self.assertIn("Communication Material", meta.get_field("doc_type").options)
		assert_permission_matrix(self, DOCTYPE)

	def test_review_due_defaults_from_settings(self):
		frappe.db.set_single_value("IC Program Settings", "doc_review_months", 24)
		doc = fx.procedure("QD-01", issued_on="2026-01-10")
		self.assertEqual(getdate(doc.review_due), getdate("2028-01-10"))
		self.assertEqual(doc.status, "Effective")
		self.assertTrue(doc.name.startswith("QTK-"))

	def test_review_due_before_issue_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			fx.procedure("QD-02", issued_on="2026-05-01", review_due="2026-04-01")

	@bru("BRU-ICP-005")
	def test_new_version_supersedes_old_and_keeps_history(self):
		old = fx.procedure("QD-03", issued_on="2025-01-01")
		new = fx.procedure("QD-03", version_no=2, supersedes=old.name)
		old.reload()
		self.assertEqual(old.status, "Superseded")
		self.assertEqual(old.superseded_by, new.name)
		self.assertEqual(new.status, "Effective")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(DOCTYPE, old.name)
		with self.assertRaises(frappe.ValidationError):
			fx.procedure("QD-03", version_no=3, supersedes=old.name)  # đã có bản thay thế
		with self.assertRaises(frappe.ValidationError):
			fx.procedure("QD-OTHER", version_no=5, supersedes=new.name)  # khác mã văn bản
		with self.assertRaises(frappe.ValidationError):
			fx.procedure("QD-03", version_no=2, supersedes=new.name)  # phiên bản không tăng

	@bru("BRU-ICP-005")
	def test_extending_review_due_returns_to_effective(self):
		doc = fx.procedure("QD-04", issued_on=add_months(today(), -12), review_due=add_days(today(), 10))
		doc.db_set("status", "Review Needed")
		doc.reload()
		doc.review_due = add_months(today(), 12)
		doc.save()
		self.assertEqual(doc.status, "Effective")

	@bru("BRU-ICP-005")
	def test_indicator_excludes_overdue_and_superseded(self):
		"""Q4: mẫu số = văn bản hiện hành tới cuối kỳ; tử số = chưa quá hạn rà soát tại cuối kỳ."""
		fx.procedure("QD-10", issued_on="2026-01-05", review_due="2027-01-05")  # còn hạn
		fx.procedure("QD-11", issued_on="2025-01-05", review_due="2026-03-01")  # quá hạn tại 31/03
		old = fx.procedure("QD-12", issued_on="2024-01-05", review_due="2027-01-01")
		fx.procedure(
			"QD-12", version_no=2, issued_on="2026-02-01", review_due="2027-02-01", supersedes=old.name
		)
		later = fx.procedure("QD-13", issued_on="2025-06-01", review_due="2027-06-01")
		fx.procedure("QD-13", version_no=2, issued_on="2026-06-01", supersedes=later.name)  # sau kỳ
		fx.procedure("QD-14", issued_on="2026-04-02")  # ban hành sau kỳ
		self.assertEqual(procedure_documents.current_documents("2026-03"), (3, 4, 4))
		self.assertEqual(procedure_documents.current_documents("2026-03", "Some Ward"), (0, 0, 0))

	def test_indicator_registered_through_hook(self):
		self.assertIn(procedure_documents.INDICATOR_METHOD, indicators.registry())
