"""Factory dữ liệu test (F-5)."""

import frappe


def make_user(email, roles=()):
	"""Tạo (hoặc lấy) System User với các role cho trước; trả email."""
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
	if roles:
		user.add_roles(*roles)
	return user.name


def make_set_unit(set_type=None, max_cycles=300, **kwargs):
	set_type = set_type or make_set_type().name
	return frappe.get_doc(
		{"doctype": "Set Unit", "set_type": set_type, "max_cycles": max_cycles, **kwargs}
	).insert()


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
