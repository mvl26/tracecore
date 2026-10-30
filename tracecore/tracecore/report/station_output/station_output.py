"""Báo cáo Station Output: sản lượng theo người và ca từ sự kiện trạm (FEAT-037, FR-M4-04).

Mỗi dòng là một nhân viên trong một ca của một ngày. ``sets_processed`` = số bộ khác nhau có kết quả Pass do người đó
ghi (Step Gate Result, ``recorded_by`` = tài khoản của nhân viên) trong khung giờ của ca; ``batches`` = số lô rửa và mẻ
tiệt khuẩn do người đó vận hành (``operator``) bắt đầu trong khung giờ. Ca qua đêm (giờ kết thúc ≤ giờ bắt đầu) kéo dài
sang ngày hôm sau.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, to_timedelta

from tracecore.tracecore.report.shift_schedule.shift_schedule import assignments_in_range, week_range


def shift_window(day, start_time, end_time):
	"""``(bắt đầu, kết thúc)`` của ca vào ngày `day`; giờ có thể là chuỗi HH:MM:SS hoặc timedelta."""
	begin = datetime.combine(day, datetime.min.time()) + to_timedelta(str(start_time or "00:00:00"))
	end = datetime.combine(day, datetime.min.time()) + to_timedelta(str(end_time or "23:59:59"))
	if end <= begin:
		end += timedelta(days=1)
	return begin, end


def _count_sets(user, begin, end):
	if not user:
		return 0
	return frappe.db.sql(
		"""select count(distinct set_unit) from `tabStep Gate Result`
		where recorded_by = %s and result = 'Pass' and recorded_at between %s and %s""",
		(user, begin, end),
	)[0][0]


def _count_batches(employee, begin, end):
	return sum(
		frappe.db.count(doctype, {"operator": employee, "started_at": ["between", [begin, end]]})
		for doctype in ("Wash Batch", "Sterilization Load")
	)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = week_range(filters)
	users = {}
	data = []
	for row in assignments_in_range(filters, from_date, to_date):
		if row.employee not in users:
			users[row.employee] = frappe.db.get_value("Employee", row.employee, "user_id")
		day = row.first_day
		while day <= row.last_day:
			begin, end = shift_window(day, row.start_time, row.end_time)
			sets = _count_sets(users[row.employee], begin, end)
			batches = _count_batches(row.employee, begin, end)
			data.append(
				{
					"date": day,
					"employee": row.employee,
					"employee_name": row.employee_name,
					"zone": row.tc_zone,
					"shift_type": row.shift_type,
					"sets_processed": sets,
					"batches": batches,
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
		{"fieldname": "sets_processed", "label": _("Sets Processed"), "fieldtype": "Int", "width": 120},
		{
			"fieldname": "batches",
			"label": _("Wash and Sterilization Batches"),
			"fieldtype": "Int",
			"width": 170,
		},
	]
	return columns, data
