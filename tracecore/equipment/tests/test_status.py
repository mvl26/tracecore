import frappe

from tracecore.equipment import status
from tracecore.tests.factories import make_equipment
from tracecore.tests.utils import IsolatedTestCase


class TestStatus(IsolatedTestCase):
	def test_set_status_changes_status_and_flag_does_not_leak(self):
		doc = make_equipment()
		status.set_status(doc.name, "Repair")
		self.assertEqual(frappe.db.get_value("Equipment", doc.name, "status"), "Repair")
		fresh = frappe.get_doc("Equipment", doc.name)
		self.assertFalse(fresh.flags.tc_equipment)
		fresh.status = "Ready"
		with self.assertRaises(frappe.ValidationError):
			fresh.save()

	def test_same_status_is_noop(self):
		doc = make_equipment()
		filters = {"ref_doctype": "Equipment", "ref_name": doc.name}
		before = frappe.db.count("Audit Log", filters)
		status.set_status(doc.name, "Ready")
		self.assertEqual(frappe.db.count("Audit Log", filters), before)

	def test_statuses_constant(self):
		self.assertEqual(status.STATUSES, ("Ready", "Locked", "Repair", "Retired"))
