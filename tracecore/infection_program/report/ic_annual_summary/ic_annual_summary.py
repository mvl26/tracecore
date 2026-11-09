"""Script Report "Tổng kết KSNK năm" (FEAT-058 AC-6; FR-M11-06, FR-M11-06.1, FR-M11-06.2; A-133 Q3).

Mỗi chỉ số của kế hoạch một dòng: nền, mục tiêu, giá trị năm (cộng dồn các tháng của ``IC Indicator Value``), trạng
thái bằng chữ. Thông điệp đầu báo cáo nêu tỷ lệ hoạt động hoàn thành và dấu "Tạm" khi năm chưa khóa. Xuất Excel bằng
nút Export của Desk.
"""

import frappe
from frappe import _

from tracecore.infection_program import annual_plan


def columns():
	return [
		{
			"fieldname": "indicator",
			"label": _("Indicator", context="IC Plan"),
			"fieldtype": "Link",
			"options": "IC Indicator",
			"width": 120,
		},
		{
			"fieldname": "indicator_name",
			"label": _("Indicator Name", context="IC Plan"),
			"fieldtype": "Data",
			"width": 260,
		},
		{
			"fieldname": "baseline",
			"label": _("Baseline", context="IC Plan"),
			"fieldtype": "Float",
			"width": 100,
		},
		{"fieldname": "target", "label": _("Target", context="IC Plan"), "fieldtype": "Float", "width": 100},
		{
			"fieldname": "value",
			"label": _("Year Value", context="IC Plan"),
			"fieldtype": "Float",
			"width": 110,
		},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 140},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.plan:
		return columns(), [], _("Choose an annual plan.")
	frappe.get_doc(annual_plan.DOCTYPE, filters.plan).check_permission("read")
	summary = annual_plan.year_summary(filters.plan)
	data = [
		{
			"indicator": row["indicator"],
			"indicator_name": row["indicator_name"],
			"baseline": row["baseline"],
			"target": row["target"],
			"value": row["value"],
			"status": row["status_label"] or _("No target direction"),
		}
		for row in summary["indicators"]
	]
	message = _("Activities completed: {0}/{1}.").format(
		summary["activities_completed"], summary["activities_total"]
	)
	if summary["provisional"]:
		message += " " + _("Provisional: the year is not closed or some months are not locked.")
	return columns(), data, message
