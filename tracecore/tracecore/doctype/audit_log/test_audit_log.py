import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import audit
from tracecore.setup.permissions import ROLE_CODES, build_custom_docperms
from tracecore.tests.factories import make_user
from tracecore.tests.utils import assert_permission_matrix, request_headers

# User -> Email Account -> Company (ERPNext) cần Setup Wizard; test tự tạo user qua factory.
test_ignore = ["User"]


class TestAuditLog(FrappeTestCase):
	def test_diff_ignores_type_drift_in_child_rows(self):
		"""F5: `1` với `1.0`, `'9100'` với `9100` trong bảng con không làm ghi lại cả bảng."""
		before = {"peripherals": [{"port": "9100", "baud_rate": 9600.0, "is_active": 1, "host": None}]}
		after = {"peripherals": [{"host": "", "is_active": 1.0, "baud_rate": 9600, "port": 9100}]}
		self.assertEqual(audit._diff(before, after), ({}, {}))
		changed = {"peripherals": [{"port": 9101, "baud_rate": 9600, "is_active": 1, "host": ""}]}
		old, new = audit._diff(before, changed)
		self.assertEqual((old, new), (before, changed))

	def test_log_inserts_row(self):
		name = audit.log(
			"Reject", ref_doctype="Zone Station", ref_name="TR-004", reason="SCAN_INVALID", new={"raw": "XYZ"}
		)
		doc = frappe.get_doc("Audit Log", name)
		self.assertEqual(doc.action, "Reject")
		self.assertEqual(doc.user, "Administrator")
		self.assertIsNotNone(doc.timestamp)
		self.assertEqual(frappe.parse_json(doc.new_value), {"raw": "XYZ"})

	def test_audit_log_cannot_be_modified(self):
		doc = frappe.get_doc("Audit Log", audit.log("Login"))
		doc.reason = "tamper"
		with self.assertRaises(audit.AuditLogImmutableError):
			doc.save()

	def test_audit_log_cannot_be_deleted_by_administrator(self):
		name = audit.log("Login")
		with self.assertRaises(audit.AuditLogImmutableError):
			frappe.delete_doc("Audit Log", name, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Audit Log", name))

	def test_native_rows_are_read_only_and_effective_matrix_matches(self):
		perms = frappe.get_all(
			"DocPerm",
			filters={"parent": "Audit Log"},
			fields=["role", "write", "delete", "create", "cancel", "amend", "submit"],
		)
		self.assertTrue(perms)
		assert_permission_matrix(self, "Audit Log")
		for perm in perms:
			for ptype in ("write", "delete", "create", "cancel", "amend", "submit"):
				self.assertFalse(perm[ptype], msg=f"{perm.role} has {ptype}")

	def test_generated_audit_read_permissions_and_no_delete(self):
		generated = {row["role"]: row for row in build_custom_docperms({"Audit Log"})}
		name = audit.log("Login")
		for code in ROLE_CODES:
			role = f"TC {code}"
			user = make_user(f"audit-{code.lower()}@example.com", roles=[role])
			self.assertEqual(
				bool(frappe.has_permission("Audit Log", "read", doc=name, user=user)),
				bool(generated.get(role, {}).get("read", 0)),
				role,
			)
			self.assertFalse(frappe.has_permission("Audit Log", "write", doc=name, user=user), role)
			self.assertFalse(frappe.has_permission("Audit Log", "delete", doc=name, user=user), role)
		manager = make_user("audit-sm@example.com", roles=["System Manager"])
		self.assertFalse(frappe.has_permission("Audit Log", "read", doc=name, user=manager))
		self.assertFalse(frappe.has_permission("Audit Log", "delete", doc=name, user=manager))

	def test_snapshot_drops_password_fields(self):
		user = frappe.new_doc("User")
		user.email = "snap@example.com"
		user.first_name = "Snap"
		user.new_password = "Secret-123!"
		snap = audit.snapshot(user)
		self.assertEqual(snap["first_name"], "Snap")
		self.assertNotIn("new_password", snap)
		self.assertNotIn("modified", snap)

	def test_context_from_headers(self):
		with request_headers({"X-TC-Station": "TR-004", "X-TC-Device": "kiosk-01", "X-Request-ID": "req-1"}):
			doc = frappe.get_doc("Audit Log", audit.log("Login"))
		self.assertEqual(doc.station, "TR-004")
		self.assertEqual(doc.device, "kiosk-01")
		self.assertEqual(doc.request_id, "req-1")

	def test_unknown_station_header_ignored(self):
		with request_headers({"X-TC-Station": "TR-999"}):
			doc = frappe.get_doc("Audit Log", audit.log("Login"))
		self.assertIsNone(doc.station)
