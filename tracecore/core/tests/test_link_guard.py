"""Link có `fetch_from` vẫn phải báo mã không tồn tại (A-65): Frappe v15 bỏ qua kiểm tra ở nhánh này."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.factories import make_department, make_employee


def _receipt(**fields):
	doc = frappe.get_doc(
		{
			"doctype": "Dirty Receipt",
			"department": make_department(),
			"receiver": make_employee().name,
			"station": "TR-001",
			**fields,
		}
	)
	doc.flags.tc_receiving = True
	return doc


class TestLinkGuard(FrappeTestCase):
	def test_unknown_value_of_a_fetched_link_is_rejected(self):
		with self.assertRaises(frappe.LinkValidationError):
			_receipt(department="NO-SUCH-DEPARTMENT").insert(ignore_permissions=True)

	def test_unknown_value_in_a_child_row_is_rejected(self):
		doc = _receipt()
		doc.append("confirm_lines", {"set_unit": "NO-SUCH-SET", "instrument": "NO-SUCH-INSTRUMENT"})
		with self.assertRaises(frappe.LinkValidationError):
			doc.insert(ignore_permissions=True)

	def test_ignore_links_flag_is_respected(self):
		doc = _receipt(department="NO-SUCH-DEPARTMENT")
		doc.flags.ignore_links = True
		self.assertTrue(doc.insert(ignore_permissions=True).name)

	def test_a_valid_link_still_fetches_its_name(self):
		employee = make_employee(first_name="Guard")
		doc = _receipt(receiver=employee.name).insert(ignore_permissions=True)
		self.assertEqual(doc.receiver_name, employee.employee_name)
