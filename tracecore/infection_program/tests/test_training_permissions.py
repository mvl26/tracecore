"""Quyền R01/R02 trên HRMS Training (FEAT-059 AC-10; plan D6; A-135 e)."""

import frappe

from tracecore.infection_program import permissions
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase


class TestTrainingPermissions(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		permissions.ensure_permissions()

	def test_r01_r02_rights_and_hr_roles_kept(self):
		for doctype, rules in permissions.PERMISSIONS.items():
			for role, ptypes in rules.items():
				row = permissions._row(doctype, role)
				for ptype in permissions.MANAGED_PTYPES:
					self.assertEqual(
						int(row.get(ptype) or 0), int(ptype in ptypes), f"{doctype}/{role}/{ptype}"
					)
			roles = set(frappe.get_all("Custom DocPerm", filters={"parent": doctype}, pluck="role"))
			self.assertIn("HR Manager", roles, doctype)  # quyền chuẩn của HRMS được sao chép, không mất

	def test_idempotent(self):
		before = frappe.db.count("Custom DocPerm", {"parent": ["in", list(permissions.PERMISSIONS)]})
		permissions.ensure_permissions()
		after = frappe.db.count("Custom DocPerm", {"parent": ["in", list(permissions.PERMISSIONS)]})
		self.assertEqual(before, after)

	def test_r02_can_submit_training_event_r11_cannot(self):
		r02 = factories.make_user("ksnk-train-perm-r02@example.com", ["TC R02"])
		r11 = factories.make_user("ksnk-train-perm-r11@example.com", ["TC R11"])
		self.assertTrue(frappe.has_permission("Training Event", "submit", user=r02))
		self.assertTrue(frappe.has_permission("Training Result", "create", user=r02))
		self.assertFalse(frappe.has_permission("Training Event", "delete", user=r02))
		self.assertFalse(frappe.has_permission("Training Event", "read", user=r11))

	def test_no_department_right_added(self):
		# khoa của dòng nhân viên lấy từ employee.department; R02 không có quyền Department (FR-M1-03)
		self.assertNotIn("Department", permissions.LINK_TARGETS)
		for role in ("TC R01", "TC R02"):
			self.assertIsNone(permissions._row("Department", role), role)
		r02 = factories.make_user("ksnk-train-perm-dept@example.com", ["TC R02"])
		self.assertFalse(frappe.has_permission("Department", "select", user=r02))
		self.assertTrue(frappe.has_permission("Employee", "read", user=r02))
