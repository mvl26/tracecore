"""Báo cáo Shift Schedule: lịch ca theo tuần (FEAT-037, FR-M4-04.2); xuất Excel/CSV bằng nút chuẩn của báo cáo."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


def week_range(filters):
	"""Khoảng ngày của báo cáo: mặc định tuần hiện tại (thứ Hai đến Chủ nhật)."""
	from_date = getdate(filters.get("from_date") or add_days(getdate(today()), -getdate(today()).weekday()))
	to_date = getdate(filters.get("to_date") or add_days(from_date, 6))
	return from_date, to_date


def assignments_in_range(filters, from_date, to_date):
	"""Shift Assignment hiệu lực (đã ghi sổ, Active) giao với khoảng ngày, kèm giờ ca; lọc theo khu và nhân viên."""
	conditions = {"docstatus": 1, "status": "Active", "start_date": ["<=", to_date]}
	if filters.get("employee"):
		conditions["employee"] = filters.employee
	if filters.get("zone"):
		conditions["tc_zone"] = filters.zone
	rows = frappe.get_all(
		"Shift Assignment",
		filters=conditions,
		fields=["name", "employee", "employee_name", "shift_type", "tc_zone", "start_date", "end_date"],
	)
	times = {row.name: row for row in frappe.get_all("Shift Type", fields=["name", "start_time", "end_time"])}
	result = []
	for row in rows:
		if row.end_date and getdate(row.end_date) < from_date:
			continue
		row.update(
			first_day=max(getdate(row.start_date), from_date),
			last_day=min(getdate(row.end_date) if row.end_date else to_date, to_date),
			start_time=times.get(row.shift_type, frappe._dict()).get("start_time"),
			end_time=times.get(row.shift_type, frappe._dict()).get("end_time"),
		)
		result.append(row)
	return result


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = week_range(filters)
	data = []
	for row in assignments_in_range(filters, from_date, to_date):
		day = row.first_day
		while day <= row.last_day:
			data.append(
				{
					"date": day,
					"employee": row.employee,
					"employee_name": row.employee_name,
					"zone": row.tc_zone,
					"shift_type": row.shift_type,
					"start_time": row.start_time,
					"end_time": row.end_time,
				}
			)
			day = add_days(day, 1)
	data.sort(key=lambda item: (item["date"], item["zone"] or "", item["employee_name"] or ""))
	columns = [
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 110},
		{
			"fieldname": "employee",
			"label": _("Employee"),
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 180},
		{
			"fieldname": "zone",
			"label": _("Work Zone"),
			"fieldtype": "Link",
			"options": "Zone Station",
			"width": 130,
		},
		{
			"fieldname": "shift_type",
			"label": _("Shift Type"),
			"fieldtype": "Link",
			"options": "Shift Type",
			"width": 140,
		},
		{"fieldname": "start_time", "label": _("Start Time"), "fieldtype": "Time", "width": 100},
		{"fieldname": "end_time", "label": _("End Time"), "fieldtype": "Time", "width": 100},
	]
	return columns, data
