"""DocType Cost Sheet (FEAT-046 Task 1; FR-M7-05, FR-M7-06; A-53 D1, D9)."""

import frappe

from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase


def make_sheet(**values):
	doc = frappe.get_doc(
		{
			"doctype": "Cost Sheet",
			"source_doctype": "Sterilization Load",
			"source_name": "ME-TEST",
			"status": "Priced",
			**values,
		}
	)
	doc.flags.tc_cost_sheet = True
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True)


class TestCostSheetDocType(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_named_gt_and_not_deletable(self):
		doc = make_sheet()
		self.assertRegex(doc.name, r"^GT-\d{4}-\d{5}$")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Cost Sheet", doc.name, ignore_permissions=True)

	def test_written_only_by_the_costing_service(self):
		doc = frappe.get_doc({"doctype": "Cost Sheet", "source_doctype": "Wash Batch", "source_name": "X"})
		doc.flags.ignore_links = True
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_pack_has_cost_total(self):
		field = frappe.get_meta("Pack").get_field("cost_total")
		self.assertTrue(field and field.read_only)

	def test_permissions_follow_matrix(self):
		expected = {"TC R01": 1, "TC R02": 1, "TC R09": 1, "TC R10": 1, "TC R03": 0, "TC R08": 0}
		for role, allowed in expected.items():
			user = make_user(f"cs-{role.split()[-1].lower()}@example.com", [role])
			self.assertEqual(int(bool(frappe.has_permission("Cost Sheet", "read", user=user))), allowed, role)
