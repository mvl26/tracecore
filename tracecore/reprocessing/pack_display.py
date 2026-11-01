"""Dữ liệu hiển thị nhãn gói `Tên bộ - Khoa (CY-…)` dùng chung T5-T8 (A-88, #1836); chỉ đọc."""

import frappe


def department_name(department):
	return frappe.db.get_value("Department", department, "department_name") if department else None


def row_of(pack):
	"""``{"cycle_id", "set_name", "department", "department_name"}`` của Cycle ID `pack`."""
	row = frappe.db.get_value("Pack", pack, ["set_name", "department"], as_dict=True) or frappe._dict()
	return {
		"cycle_id": pack,
		"set_name": row.set_name,
		"department": row.department,
		"department_name": department_name(row.department),
	}
