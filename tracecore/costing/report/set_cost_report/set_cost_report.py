"""Set Cost Report: giá thành gói theo loại bộ / khoa / phương pháp / Cycle ID trong kỳ, so với kỳ liền trước
(FEAT-046; FR-M7-06.1, EI-SW-006; UC-29 bước 6; A-53 j).

Nguồn là `Cost Sheet Pack` của Cost Sheet chính (bỏ bản tính lại) có ngày giá thành trong kỳ. Kỳ trước = cùng số ngày
ngay trước ngày bắt đầu (lọc theo tháng thì là tháng trước). Xuất Excel/CSV bằng nút Export chuẩn của báo cáo.
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, getdate

GROUPS = {
	"Set Type": "set_type",
	"Department": "department",
	"Method": "method",
	"Cycle ID": "pack",
}


def _columns():
	return [
		{"fieldname": "group", "label": _("Group"), "fieldtype": "Data", "width": 200},
		{"fieldname": "packs", "label": _("Packs"), "fieldtype": "Int", "width": 90},
		{"fieldname": "total", "label": _("Total Cost"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "average", "label": _("Cost per Pack"), "fieldtype": "Currency", "width": 140},
		{
			"fieldname": "previous_average",
			"label": _("Previous Period per Pack"),
			"fieldtype": "Currency",
			"width": 160,
		},
		{"fieldname": "change_percent", "label": _("Change %"), "fieldtype": "Percent", "width": 100},
	]


def _totals(field, date_from, date_to):
	"""{nhóm: (số gói, tổng)} của các gói trong khoảng ngày."""
	sheets = frappe.get_all(
		"Cost Sheet",
		filters={"is_recalculation": 0, "cost_date": ["between", [date_from, date_to]]},
		pluck="name",
	)
	if not sheets:
		return {}
	totals = {}
	for row in frappe.get_all(
		"Cost Sheet Pack",
		filters={"parent": ["in", sheets], "parenttype": "Cost Sheet"},
		fields=[field, "total"],
	):
		packs, total = totals.get(row[field], (0, 0))
		totals[row[field]] = (packs + 1, total + flt(row.total))
	return totals


def execute(filters=None):
	filters = frappe._dict(filters or {})
	field = GROUPS.get(filters.get("group_by") or "Set Type")
	if not field:
		frappe.throw(_("Group by must be one of: {0}").format(", ".join(GROUPS)))
	date_from, date_to = getdate(filters.from_date), getdate(filters.to_date)
	days = date_diff(date_to, date_from) + 1
	current = _totals(field, date_from, date_to)
	previous = _totals(field, add_days(date_from, -days), add_days(date_from, -1))
	data = []
	for group, (packs, total) in sorted(current.items(), key=lambda item: str(item[0] or "")):
		average = flt(total / packs) if packs else 0
		before_packs, before_total = previous.get(group, (0, 0))
		before = flt(before_total / before_packs) if before_packs else 0
		data.append(
			{
				"group": group,
				"packs": packs,
				"total": total,
				"average": average,
				"previous_average": before,
				"change_percent": flt((average - before) / before * 100, 2) if before else None,
			}
		)
	return _columns(), data
