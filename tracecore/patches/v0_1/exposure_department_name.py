"""Hồ sơ phơi nhiễm bị form Desk xóa Khoa (fetch_from employee.department ghi đè rỗng khi nhân viên chưa gán khoa) nhưng
còn Tên khoa cũ: đúng 1 Department có tên đó thì gán lại Khoa, ngược lại xóa Tên khoa. Không đổi ``modified``."""

import frappe

DOCTYPE = "Occupational Exposure"


def execute():
	if not frappe.db.table_exists(DOCTYPE):
		return
	rows = frappe.get_all(
		DOCTYPE,
		filters={"department": ["is", "not set"], "department_name": ["is", "set"]},
		fields=["name", "department_name"],
	)
	for row in rows:
		matches = frappe.get_all("Department", filters={"department_name": row.department_name}, pluck="name")
		values = {"department": matches[0]} if len(matches) == 1 else {"department_name": None}
		frappe.db.set_value(DOCTYPE, row.name, values, update_modified=False)
