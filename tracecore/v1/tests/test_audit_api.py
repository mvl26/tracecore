import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import audit
from tracecore.tests.factories import make_user
from tracecore.v1 import audit as api


class TestAuditApi(FrappeTestCase):
	def test_audit_query_filters(self):
		audit.log("Login", ref_doctype="Zone Station", ref_name="TR-003")
		audit.log("Reject", ref_doctype="Zone Station", ref_name="TR-003", reason="X")
		audit.log("Login", ref_doctype="Zone Station", ref_name="TR-002")
		rows = api.query(ref_doctype="Zone Station", ref_name="TR-003")
		self.assertGreaterEqual(len(rows), 2)
		self.assertTrue(all(row["ref_name"] == "TR-003" for row in rows))
		self.assertEqual(len(api.query(ref_doctype="Zone Station", ref_name="TR-003", limit=1)), 1)

	def test_audit_query_requires_permission(self):
		frappe.set_user(make_user("audit-noperm@example.com", roles=["TC R04"]))
		try:
			with self.assertRaises(frappe.PermissionError):
				api.query(ref_doctype="Zone Station")
		finally:
			frappe.set_user("Administrator")
