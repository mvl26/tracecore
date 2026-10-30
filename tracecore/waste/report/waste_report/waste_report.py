"""Báo cáo chất thải theo kỳ, khoa, loại (FEAT-050, UC-37, SCR-41, FR-M10-07, .2, FR-M10-08.3, A-63).

In và xuất Excel bằng công cụ chuẩn của Report; cột Trạng thái kỳ ghi Tạm khi kỳ chưa khóa. Mẫu phụ lục TT 20/2021 chưa làm vì
chờ bản mẫu của khoa KSNK (UC-37 Open issues).
"""

from frappe import _
from frappe.utils import add_months, get_first_day, get_last_day, today

from tracecore.waste import analysis


def _columns():
	return [
		{
			"fieldname": "department",
			"label": _("Department"),
			"fieldtype": "Link",
			"options": "Department",
			"width": 170,
		},
		{
			"fieldname": "waste_type",
			"label": _("Waste Type"),
			"fieldtype": "Link",
			"options": "Waste Type",
			"width": 170,
		},
		{"fieldname": "bags", "label": _("Bags or Bins"), "fieldtype": "Int", "width": 80},
		{
			"fieldname": "collected_kg",
			"label": _("Collected (kg)"),
			"fieldtype": "Float",
			"precision": 3,
			"width": 100,
		},
		{
			"fieldname": "handover_kg",
			"label": _("Handed Over (kg)"),
			"fieldtype": "Float",
			"precision": 3,
			"width": 110,
		},
		{
			"fieldname": "difference_kg",
			"label": _("Difference (kg)"),
			"fieldtype": "Float",
			"precision": 3,
			"width": 100,
		},
		{"fieldname": "cost", "label": _("Treatment Cost"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "cost_per_kg", "label": _("Cost per kg"), "fieldtype": "Currency", "width": 100},
		{
			"fieldname": "compliance_percent",
			"label": _("Storage Compliance (%)"),
			"fieldtype": "Percent",
			"width": 110,
		},
		{"fieldname": "bags_per_day", "label": _("Bags per Day"), "fieldtype": "Float", "width": 90},
		{
			"fieldname": "kg_per_bed_day",
			"label": _("Kg per Bed per Day"),
			"fieldtype": "Float",
			"precision": 3,
			"width": 100,
		},
		{"fieldname": "alerts", "label": _("Waste Alerts"), "fieldtype": "Data", "width": 200},
		{"fieldname": "report_status", "label": _("Period Status"), "fieldtype": "Data", "width": 100},
	]


def execute(filters=None):
	filters = filters or {}
	last_month = add_months(today(), -1)
	from_date = filters.get("from_date") or get_first_day(last_month)
	to_date = filters.get("to_date") or get_last_day(last_month)
	status = "Provisional" if analysis.is_provisional(to_date) else "Final"
	rows = analysis.report_rows(from_date, to_date, filters.get("department"), filters.get("waste_type"))
	for row in rows:
		alerts = []
		if row["quota_missing"]:
			alerts.append(_("No quota"))
		if row["repeat_misclassification"]:
			alerts.append(_("Repeated misclassification"))
		row["alerts"] = "; ".join(alerts)
		row["report_status"] = status
	return _columns(), rows
