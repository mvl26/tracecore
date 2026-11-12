"""Số liệu báo cáo nước thải (FEAT-095; FR-M15-12, .1; AC-095-12).

``summary``: bảng điểm x thông số x đợt kèm giới hạn (bản chụp) và số lần vượt — nguồn chung cho Script Report
"Wastewater Monitoring Summary" và SCR-67, nên số liệu khớp nhau. ``brief``: dòng tóm tắt cho báo cáo môi trường
tháng/quý (FR-M15-07). TraceCore chỉ xuất số liệu, không nộp báo cáo lên Sở/Bộ.
"""

import frappe
from frappe.utils import getdate

from tracecore.environmental_hygiene import wastewater, wastewater_schedule

ROUND_FIELDS = [
	"name",
	"wastewater_point",
	"point_name",
	"point_type",
	"sampled_on",
	"period_label",
	"supplier",
	"supplier_name",
	"vimcerts_no",
	"report_no",
	"wastewater_permit",
	"standard_applied",
	"overall_result",
	"is_remonitor_of",
	"nc_status",
	"nc_name",
]


def rounds(start, end, point=None):
	filters = {"docstatus": 1, "sampled_on": ["between", [getdate(start), getdate(end)]]}
	if point:
		filters["wastewater_point"] = point
	return frappe.get_all(
		wastewater.DOCTYPE, filters=filters, fields=ROUND_FIELDS, order_by="sampled_on asc, creation asc"
	)


def results(names):
	if not names:
		return {}
	rows = frappe.get_all(
		wastewater.RESULT_DOCTYPE,
		filters={"parenttype": wastewater.DOCTYPE, "parent": ["in", list(names)]},
		fields=["parent", "idx", "parameter", "unit", "value", "below_detection", "limit_applied", "result"],
		order_by="parent asc, idx asc",
	)
	by_round = {}
	for row in rows:
		by_round.setdefault(row.parent, []).append(row)
	return by_round


def summary(start, end, point=None):
	data = rounds(start, end, point)
	by_round = results([row.name for row in data])
	rows, exceed = [], {}
	for item in data:
		for result in by_round.get(item.name, []):
			rows.append(
				{
					"point": item.wastewater_point,
					"point_name": item.point_name,
					"monitoring": item.name,
					"sampled_on": item.sampled_on,
					"supplier_name": item.supplier_name,
					"parameter": result.parameter,
					"unit": result.unit,
					"value": result.value,
					"below_detection": result.below_detection,
					"limit_applied": result.limit_applied,
					"result": result.result,
				}
			)
			key = (item.wastewater_point, result.parameter)
			exceed.setdefault(key, 0)
			if result.result == wastewater.FAIL:
				exceed[key] += 1
	return {
		"rounds": len(data),
		"failed": sum(1 for item in data if item.overall_result == wastewater.FAIL),
		"rows": rows,
		"exceed": exceed,
		"items": data,
	}


def brief(start, end):
	"""Dòng nước thải trong báo cáo môi trường (FR-M15-12.1)."""
	data = rounds(start, end)
	end = getdate(end)
	overdue = sum(
		1
		for row in wastewater_schedule.grid(end.year, on=end)
		for cell in row["periods"]
		if cell["status"] in (wastewater_schedule.OVER, wastewater_schedule.MISS)
		and getdate(start) <= cell["end"] < end
	)
	return {
		"rounds": len(data),
		"failed": sum(1 for item in data if item.overall_result == wastewater.FAIL),
		"overdue": overdue,
	}
