"""RPC tracecore.v1.staff.* — danh sách chứng chỉ của nhân viên cho form Employee trên Desk (FEAT-036, SCR-19)."""

import frappe
from frappe.utils import add_days, today

from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import staff as api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def make_certificate(employee, days, certificate_type="Sterilization", **fields):
	return frappe.get_doc(
		{
			"doctype": "Certificate",
			"employee": employee,
			"certificate_type": certificate_type,
			"certificate_no": "CC-" + frappe.generate_hash(length=8),
			"issued_on": add_days(today(), -400),
			"no_expiry": 1 if days is None else 0,
			"expires_on": None if days is None else add_days(today(), days),
			**fields,
		}
	).insert(ignore_permissions=True)


class TestStaffApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user("staff-api-r02@example.com", ["TC R02"])
		self.r04 = make_user("staff-api-r04@example.com", ["TC R04"])
		self.employee = make_employee(first_name="Hồ sơ").name
		self.addCleanup(frappe.set_user, "Administrator")

	def test_certificates_summary_counts_and_days_left(self):
		valid = make_certificate(self.employee, 100)
		soon = make_certificate(self.employee, 10, certificate_type="Infection Control")
		expired = make_certificate(self.employee, -2, certificate_type="Other")
		forever = make_certificate(self.employee, None, certificate_type="Practice License")
		frappe.set_user(self.r02)
		result = api.certificates(self.employee)
		self.assertTrue(result["ok"])
		by_name = {row["name"]: row for row in result["rows"]}
		self.assertEqual(by_name[valid.name]["days_left"], 100)
		self.assertEqual(by_name[expired.name]["status"], "Expired")
		self.assertIsNone(by_name[forever.name]["days_left"])
		self.assertEqual(result["counts"], {"valid": 3, "expiring": 1, "expired": 1})
		self.assertEqual(by_name[soon.name]["expiring"], 1)

	def test_superseded_certificates_are_listed_but_not_counted(self):
		old = make_certificate(self.employee, 5)
		make_certificate(self.employee, 400, renews=old.name)
		frappe.set_user(self.r02)
		result = api.certificates(self.employee)
		self.assertEqual(len(result["rows"]), 2)
		self.assertEqual(result["counts"], {"valid": 1, "expiring": 0, "expired": 0})

	def test_user_without_certificate_permission_is_refused(self):
		make_certificate(self.employee, 10)
		frappe.set_user(self.r04)
		with self.assertRaises(frappe.PermissionError):
			api.certificates(self.employee)

	def test_unknown_employee(self):
		frappe.set_user(self.r02)
		with self.assertRaises(frappe.DoesNotExistError):
			api.certificates("NV-99999")
