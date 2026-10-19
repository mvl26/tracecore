"""Factory dữ liệu test (F-5)."""

import frappe


def make_set_type(type_code="TST", method="Steam", set_type_name=None):
	if frappe.db.exists("Instrument Set Type", type_code):
		return frappe.get_doc("Instrument Set Type", type_code)
	return frappe.get_doc(
		{
			"doctype": "Instrument Set Type",
			"type_code": type_code,
			"set_type_name": set_type_name or f"Test set {type_code}",
			"method": method,
		}
	).insert()
