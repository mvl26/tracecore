"""Script Report "Kháng thuốc theo quý" (FEAT-067; FR-M14-08, FR-M14-08.1; BRU-MDR-002; QĐ 3596; A-136 Q8).

S/I/R % theo vi khuẩn-kháng sinh (tùy chọn theo khoa) chỉ trên chủng đầu tiên của quý; cặp có ít chủng hơn ngưỡng
hiện cảnh báo bằng chữ. Chỉ số liệu tổng hợp, không có mã người bệnh — R13 xem được (ADR-010).
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from tracecore.microbiology import resistance


def _columns(by_department):
	columns = [
		{
			"fieldname": "organism",
			"label": _("Organism", context="Microbiology Isolate"),
			"fieldtype": "Link",
			"options": "Organism",
			"width": 90,
		},
		{"fieldname": "organism_name", "label": _("Organism Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "antibiotic", "label": _("Antibiotic Code"), "fieldtype": "Data", "width": 110},
		{"fieldname": "antibiotic_name", "label": _("Antibiotic Name"), "fieldtype": "Data", "width": 160},
	]
	if by_department:
		columns.append(
			{"fieldname": "department_name", "label": _("Department"), "fieldtype": "Data", "width": 180}
		)
	columns += [
		{"fieldname": "tested", "label": _("Isolates Tested"), "fieldtype": "Int", "width": 110},
		{"fieldname": "s_pct", "label": _("S %"), "fieldtype": "Percent", "width": 80},
		{"fieldname": "i_pct", "label": _("I %"), "fieldtype": "Percent", "width": 80},
		{"fieldname": "r_pct", "label": _("R %"), "fieldtype": "Percent", "width": 80},
		{"fieldname": "warning", "label": _("Note"), "fieldtype": "Data", "width": 240},
	]
	return columns


def execute(filters=None):
	filters = frappe._dict(filters or {})
	year = cint(filters.year) or getdate(today()).year
	quarter = cint(filters.quarter) or (getdate(today()).month - 1) // 3 + 1
	by_department = cint(filters.by_department)
	threshold = resistance.min_isolates()
	rows = resistance.compute(
		year, quarter, department=filters.department, organism=filters.organism, by_department=by_department
	)
	for row in rows:
		row["warning"] = (
			_("Small sample: fewer than {0} first isolates").format(threshold) if row["small_sample"] else ""
		)
		row.pop("small_sample")
	first = resistance.first_isolate_count(year, quarter, filters.department, filters.organism)
	rate = resistance.hai_with_pathogen_rate(year, quarter)
	summary = [
		{"label": _("First isolates in the quarter"), "value": first, "datatype": "Int", "indicator": "Blue"},
		{"label": _("Small sample threshold"), "value": threshold, "datatype": "Int", "indicator": "Grey"},
		{
			"label": _("Confirmed HAI cases with a pathogen"),
			"value": _("{0} %").format(rate) if rate is not None else _("No HAI surveillance data yet"),
			"datatype": "Data",
			"indicator": "Grey",
		},
	]
	message = _("Quarter {0}/{1}: only the first isolate of each patient and organism is counted.").format(
		quarter, year
	)
	return _columns(by_department), rows, message, None, summary
