"""Dự báo bộ dụng cụ hết vòng đời 12 tháng tới kèm giá thay (FEAT-007, FR-M9-02, A-57 Q4).

Dữ liệu ở `admin_reports.sterilization_log.life_forecast`; sau mỗi tháng có dòng tổng tiền (``is_total``).
"""

from frappe import _

from tracecore.admin_reports import sterilization_log


def _columns():
	return [
		{"fieldname": "month", "label": _("Month"), "fieldtype": "Data", "width": 90},
		{
			"fieldname": "set_unit",
			"label": _("Set ID"),
			"fieldtype": "Link",
			"options": "Set Unit",
			"width": 170,
		},
		{"fieldname": "set_type_name", "label": _("Set Type"), "fieldtype": "Data", "width": 180},
		{
			"fieldname": "department",
			"label": _("Department"),
			"fieldtype": "Link",
			"options": "Department",
			"width": 150,
		},
		{"fieldname": "cycles_used", "label": _("Cycles Used"), "fieldtype": "Int", "width": 90},
		{"fieldname": "max_cycles", "label": _("Maximum Cycles"), "fieldtype": "Int", "width": 90},
		{"fieldname": "remaining", "label": _("Cycles Remaining"), "fieldtype": "Int", "width": 90},
		{"fieldname": "cycles_per_month", "label": _("Cycles per Month"), "fieldtype": "Float", "width": 90},
		{"fieldname": "price", "label": _("Replacement Price (VND)"), "fieldtype": "Currency", "width": 140},
	]


def execute(filters=None):
	rows, month, total = [], None, 0
	for row in sterilization_log.life_forecast(filters):
		if month and row["month"] != month:
			rows.append(_total(month, total))
			total = 0
		month = row["month"]
		total += row["price"]
		rows.append(row)
	if month:
		rows.append(_total(month, total))
	return _columns(), rows


def _total(month, total):
	return {"month": month, "set_type_name": _("Total {0}").format(month), "price": total, "is_total": 1}
