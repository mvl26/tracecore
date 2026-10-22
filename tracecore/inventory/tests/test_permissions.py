import frappe

from tracecore.inventory import permissions
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

CONSUMABLE_DOCTYPES = ("Item", "Batch", "Stock Entry")
LINK_TARGETS = ("Supplier", "Warehouse", "Item Group", "UOM", "Company", "Stock Entry Type")
RECEIPT_ROLES = ("TC R09", "TC R06")


def user_for(role):
	"""Người dùng thử chỉ có đúng một vai trò."""
	return factories.make_user(f"perm-{role.replace(chr(32), chr(45)).lower()}@example.com", [role])


class TestInventoryPermissions(IsolatedTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		permissions.ensure_permissions()

	def test_matrix_applied_for_each_role(self):
		checked = 0
		for doctype, rules in permissions.PERMISSION_MATRIX.items():
			for role, ptypes in rules.items():
				user = user_for(role)
				for ptype in permissions.MANAGED_PTYPES:
					expected = ptype in ptypes
					if ptype == "report" and not expected:
						continue  # vai trò chuẩn "Desk User" của ERPNext đã cho mọi người dùng Desk quyền report
					actual = bool(frappe.has_permission(doctype, ptype, user=user))
					self.assertEqual(actual, expected, msg=f"{doctype} / {role} / {ptype}")
					checked += 1
		self.assertGreater(checked, 100)

	def test_receipt_roles_can_create_and_submit(self):
		for role in RECEIPT_ROLES:
			user = user_for(role)
			for doctype, ptypes in (
				("Stock Entry", ("read", "create", "write", "submit")),
				("Batch", ("read", "create", "write")),
			):
				for ptype in ptypes:
					self.assertTrue(
						frappe.has_permission(doctype, ptype, user=user), msg=f"{role} {doctype} {ptype}"
					)
		self.assertTrue(frappe.has_permission("Item", "create", user=user_for("TC R09")))
		self.assertFalse(frappe.has_permission("Item", "create", user=user_for("TC R06")))

	def test_report_manager_is_read_only(self):
		user = user_for("TC R01")
		for doctype in CONSUMABLE_DOCTYPES:
			self.assertTrue(frappe.has_permission(doctype, "read", user=user), msg=doctype)
			for ptype in ("create", "write", "submit", "cancel"):
				self.assertFalse(frappe.has_permission(doctype, ptype, user=user), msg=f"{doctype} {ptype}")

	def test_nobody_can_delete_stock_entry_item_batch(self):
		for role in ("TC R09", "TC R06", "TC R10", "TC R02", "System Manager"):
			user = user_for(role)
			for doctype in CONSUMABLE_DOCTYPES:
				self.assertFalse(frappe.has_permission(doctype, "delete", user=user), msg=f"{role} {doctype}")
		for doctype in CONSUMABLE_DOCTYPES:
			rows = frappe.get_all("Custom DocPerm", filters={"parent": doctype, "delete": 1})
			self.assertEqual(rows, [], msg=doctype)

	def test_cancel_only_r09_r02_system_manager(self):
		allowed = {"TC R09", "TC R02", "System Manager"}
		for role in ("TC R09", "TC R06", "TC R10", "TC R02", "TC R01", "System Manager"):
			self.assertEqual(
				bool(frappe.has_permission("Stock Entry", "cancel", user=user_for(role))),
				role in allowed,
				msg=role,
			)

	def test_link_targets_readable_for_receipt_roles(self):
		for role in RECEIPT_ROLES:
			user = user_for(role)
			for doctype in LINK_TARGETS:
				self.assertTrue(frappe.has_permission(doctype, "read", user=user), msg=f"{role} {doctype}")

	def test_ensure_permissions_idempotent(self):
		permissions.ensure_permissions()
		before = frappe.db.count("Custom DocPerm")
		snapshot = frappe.get_all(
			"Custom DocPerm", fields=["name", "parent", "role", "modified"], order_by="name"
		)
		permissions.ensure_permissions()
		self.assertEqual(frappe.db.count("Custom DocPerm"), before)
		self.assertEqual(
			frappe.get_all("Custom DocPerm", fields=["name", "parent", "role", "modified"], order_by="name"),
			snapshot,
		)

	def test_ensure_permissions_restores_a_removed_right(self):
		name = frappe.db.get_value(
			"Custom DocPerm", {"parent": "Stock Entry", "role": "TC R06", "permlevel": 0}
		)
		self.assertTrue(name)
		frappe.db.set_value("Custom DocPerm", name, "submit", 0)
		frappe.clear_cache(doctype="Stock Entry")
		self.assertFalse(frappe.has_permission("Stock Entry", "submit", user=user_for("TC R06")))
		permissions.ensure_permissions()
		self.assertTrue(frappe.has_permission("Stock Entry", "submit", user=user_for("TC R06")))
