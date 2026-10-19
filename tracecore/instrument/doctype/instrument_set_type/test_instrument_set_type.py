import frappe
from frappe.tests.utils import FrappeTestCase


class TestInstrumentSetType(FrappeTestCase):
	def test_set_type_code_validation(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Instrument Set Type", "type_code": "bpt 1", "set_type_name": "X", "method": "Steam"}
			).insert()

		doc = frappe.get_doc(
			{"doctype": "Instrument Set Type", "type_code": "zz9t", "set_type_name": "Bo test", "method": "Plasma"}
		).insert()
		self.assertEqual(doc.name, "ZZ9T")
		self.assertEqual(doc.type_code, "ZZ9T")
