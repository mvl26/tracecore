"""FEAT-004, A-37 (c)(d): xóa danh mục (FR-M9-16) và báo cáo Audit Trail (NFR-SEC-03)."""

import frappe

from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.tracecore.report.audit_trail import audit_trail

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestMasterDelete(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r10 = make_user("md-r10@example.com", ["TC R10", "System Manager"])
		self.r02 = make_user("md-r02@example.com", ["TC R02", "System Manager"])
		self.addCleanup(frappe.set_user, "Administrator")

	def test_r10_hard_deletes_an_unused_master(self):
		location = factories.make_sterile_location("Kệ chưa dùng").name
		frappe.set_user(self.r10)
		frappe.delete_doc("Sterile Location", location, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Sterile Location", location))
		self.assertEqual(frappe.db.get_value("Code Registry", location, "status"), "Disabled")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{
					"ref_doctype": "Sterile Location",
					"ref_name": location,
					"action": "Delete",
					"user": self.r10,
				},
			)
		)

	def test_master_with_transactions_or_other_roles_cannot_be_deleted(self):
		used = factories.make_stocked_pack()
		location = frappe.db.get_value("Pack", used.name, "location")
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Sterile Location", location, ignore_permissions=True)
		frappe.set_user("Administrator")
		unused = factories.make_sterile_location("Kệ khác").name
		frappe.set_user(self.r02)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Sterile Location", unused, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Sterile Location", unused))


class TestAuditTrail(IsolatedTestCase):
	def test_report_lists_audit_rows_with_filters(self):
		unit = factories.make_set_unit()
		columns, rows = audit_trail.execute({"ref_doctype": "Set Unit", "ref_name": unit.name})[:2]
		self.assertIn("action", [column["fieldname"] for column in columns])
		self.assertTrue(rows)
		self.assertEqual({row["ref_name"] for row in rows}, {unit.name})
		self.assertEqual(audit_trail.execute({"ref_name": "KHONG-CO"})[1], [])
