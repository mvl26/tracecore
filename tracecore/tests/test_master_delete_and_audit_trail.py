"""FEAT-004, A-37 (c)(d), A-164: xóa danh mục (FR-M9-16) và báo cáo Audit Trail (NFR-SEC-03)."""

import frappe
from frappe.utils import now_datetime

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


class TestEmployeeDelete(IsolatedTestCase):
	"""A-164: R10 và Administrator xóa cứng nhân viên chưa có giao dịch; đã có giao dịch thì chỉ cho nghỉ (Left)."""

	def setUp(self):
		super().setUp()
		self.r10 = make_user("ed-r10@example.com", ["TC R10"])
		self.r02 = make_user("ed-r02@example.com", ["TC R02", "System Manager"])
		self.sysman = make_user("ed-sm@example.com", ["System Manager"])
		self.addCleanup(frappe.set_user, "Administrator")

	def _assert_deleted(self, employee, user):
		self.assertFalse(frappe.db.exists("Employee", employee))
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": "Employee", "ref_name": employee, "action": "Delete", "user": user},
			)
		)
		codes = frappe.get_all(
			"Code Registry", filters={"ref_doctype": "Employee", "ref_name": employee}, pluck="status"
		)
		if employee.startswith("NV-"):
			self.assertTrue(codes)
		self.assertEqual(set(codes) - {"Disabled"}, set())

	def test_r10_hard_deletes_employee_without_transactions(self):
		employee = factories.make_employee(first_name="Xóa thử").name
		frappe.set_user(self.r10)
		frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self._assert_deleted(employee, self.r10)

	def test_administrator_hard_deletes_employee_without_transactions(self):
		employee = factories.make_employee(first_name="Xóa thử Admin").name
		frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self._assert_deleted(employee, "Administrator")

	def test_employee_with_certificate_cannot_be_deleted(self):
		employee = factories.make_employee(first_name="Có chứng chỉ").name
		frappe.get_doc(
			{
				"doctype": "Certificate",
				"employee": employee,
				"certificate_type": "Sterilization",
				"certificate_no": "CC-" + frappe.generate_hash(length=8),
				"issued_on": "2025-01-01",
				"no_expiry": 1,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Employee", employee))

	def test_employee_with_station_session_cannot_be_deleted(self):
		employee = factories.make_employee(first_name="Có phiên trạm").name
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Session",
				"employee": employee,
				"user": "Administrator",
				"station": "TRAM-GIA",
				"token_hash": frappe.generate_hash(length=32),
				"started_at": now,
				"last_activity_at": now,
				"absolute_expires_at": now,
			}
		).insert(ignore_permissions=True, ignore_links=True)
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Employee", employee))

	def test_employee_with_login_account_cannot_be_deleted(self):
		employee = factories.make_employee(first_name="Có tài khoản", user_id=self.r02).name
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Employee", employee))

	def test_other_roles_cannot_delete_employee(self):
		employee = factories.make_employee(first_name="Không quyền").name
		for user in (self.r02, self.sysman):
			frappe.set_user(user)
			with self.assertRaises(frappe.ValidationError):
				frappe.delete_doc("Employee", employee, ignore_permissions=True)
			frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Employee", employee))


class TestAuditTrail(IsolatedTestCase):
	def test_report_lists_audit_rows_with_filters(self):
		unit = factories.make_set_unit()
		columns, rows = audit_trail.execute({"ref_doctype": "Set Unit", "ref_name": unit.name})[:2]
		self.assertIn("action", [column["fieldname"] for column in columns])
		self.assertTrue(rows)
		self.assertEqual({row["ref_name"] for row in rows}, {unit.name})
		self.assertEqual(audit_trail.execute({"ref_name": "KHONG-CO"})[1], [])
