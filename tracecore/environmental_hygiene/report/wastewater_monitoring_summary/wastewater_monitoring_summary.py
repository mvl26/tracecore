"""Script Report "Wastewater Monitoring Summary" — báo cáo nước thải theo kỳ hoặc năm (FEAT-095; FR-M15-12; AC-095-12).

Phần 1: từng điểm x đợt x thông số kèm giới hạn đã áp dụng (bản chụp) và kết quả. Phần 2: số lần vượt theo điểm x
thông số. Xuất Excel bằng nút Export của Frappe, PDF bằng In — dùng làm phụ lục báo cáo công tác bảo vệ môi trường năm
(TT 02/2022/TT-BTNMT); TraceCore không nộp thay.
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from tracecore.environmental_hygiene import wastewater_report


def columns():
	return [
		{"fieldname": "section", "label": _("Section"), "fieldtype": "Data", "width": 160},
		{"fieldname": "point_name", "label": _("Point"), "fieldtype": "Data", "width": 160},
		{
			"fieldname": "monitoring",
			"label": _("Round"),
			"fieldtype": "Link",
			"options": "Wastewater Monitoring",
			"width": 140,
		},
		{"fieldname": "sampled_on", "label": _("Sampled On"), "fieldtype": "Date", "width": 100},
		{"fieldname": "supplier_name", "label": _("Monitoring Unit"), "fieldtype": "Data", "width": 160},
		{"fieldname": "parameter", "label": _("Parameter"), "fieldtype": "Data", "width": 140},
		{"fieldname": "unit", "label": _("Unit"), "fieldtype": "Data", "width": 90},
		{"fieldname": "value_text", "label": _("Value"), "fieldtype": "Data", "width": 100},
		{"fieldname": "limit_applied", "label": _("Limit Applied"), "fieldtype": "Data", "width": 300},
		{"fieldname": "result", "label": _("Result"), "fieldtype": "Data", "width": 90},
		{"fieldname": "exceed", "label": _("Times Exceeded"), "fieldtype": "Int", "width": 110},
	]


def _value(row):
	if row["below_detection"]:
		return _("Not detected")
	return frappe.format(row["value"], "Float") if row["value"] else ""


def rows(data):
	out = []
	for row in data["rows"]:
		out.append(
			{
				**{key: row[key] for key in ("point_name", "monitoring", "sampled_on", "supplier_name")},
				"parameter": row["parameter"],
				"unit": row["unit"],
				"value_text": _value(row),
				"limit_applied": row["limit_applied"],
				"result": _(row["result"]) if row["result"] else "",
			}
		)
	names = {row["point"]: row["point_name"] for row in data["rows"]}
	for (point, parameter), count in sorted(data["exceed"].items()):
		out.append(
			{
				"section": _("Times exceeded"),
				"point_name": names.get(point, point),
				"parameter": parameter,
				"exceed": count,
			}
		)
	return out


def execute(filters=None):
	filters = frappe._dict(filters or {})
	end = getdate(filters.to_date or today())
	start = getdate(filters.from_date or f"{end.year}-01-01")
	data = wastewater_report.summary(start, end, filters.wastewater_point)
	message = _("{0} rounds, {1} failed, {2} - {3}.").format(
		data["rounds"], data["failed"], frappe.format(start, "Date"), frappe.format(end, "Date")
	)
	return columns(), rows(data), message
