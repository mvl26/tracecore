"""Script Report "Environmental Hygiene" — báo cáo môi trường tháng/quý (FEAT-070; FR-M15-07, .1; UC-54 bước 8).

Một bảng nhiều phần: giám sát vệ sinh theo mức nguy cơ / khoa / bên chịu trách nhiệm, vùng thiếu phiếu, xét nghiệm môi
trường theo loại mẫu, mẫu trễ hạn, hạ tầng theo loại (đúng hạn), lít hóa chất khử khuẩn bề mặt theo khoa. Xuất Excel bằng
nút Export của Frappe, PDF bằng In (FR-M15-07.1).
"""

import frappe
from frappe import _

from tracecore.environmental_hygiene import report_data


def columns():
	return [
		{"fieldname": "section", "label": _("Section"), "fieldtype": "Data", "width": 200},
		{"fieldname": "item", "label": _("Item"), "fieldtype": "Data", "width": 240},
		{"fieldname": "total", "label": _("Total"), "fieldtype": "Float", "precision": 0, "width": 90},
		{
			"fieldname": "passed",
			"label": _("Passed / On Time"),
			"fieldtype": "Float",
			"precision": 0,
			"width": 120,
		},
		{"fieldname": "pct", "label": _("Rate (%)"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 260},
	]


def _rate(passed, total):
	return round(passed * 100 / total, 1) if total else None


def rows(data):
	out = []
	hygiene = data["hygiene"]
	for title, key in (
		(_("Cleaning audits by risk level"), "by_risk"),
		(_("Cleaning audits by department"), "by_department"),
		(_("Cleaning audits by responsible party"), "by_party"),
	):
		for entry in hygiene[key]:
			out.append(
				{
					"section": title,
					"item": entry["label"],
					"total": entry["total"],
					"passed": entry["passed"],
					"pct": entry["pct"],
				}
			)
	passed, total = data["high_risk"]
	out.append(
		{
			"section": _("Surface cleaning of high-risk areas"),
			"item": _("All high-risk zones"),
			"total": total,
			"passed": passed,
			"pct": _rate(passed, total),
			"note": _("QD 38 target: at least 80 %"),
		}
	)
	for zone in data["coverage"]:
		out.append(
			{
				"section": _("Zones short of minimum audits"),
				"item": f"{zone['area_name']} — {zone['department_name'] or zone['department']}",
				"total": zone["required"],
				"passed": zone["done"],
				"note": _("Awaiting resample") if zone["awaiting_resample"] else "",
			}
		)
	samples = data["samples"]
	for entry in samples["by_type"]:
		out.append(
			{
				"section": _("Environmental tests"),
				"item": _(entry["key"]),
				"total": entry["total"],
				"passed": entry["total"] - entry["failed"],
				"pct": _rate(entry["total"] - entry["failed"], entry["total"]),
			}
		)
	for row in data["overdue_samples"]:
		out.append(
			{
				"section": _("Overdue samples"),
				"item": f"{row['area_name'] or row['zone']} — {_(row['sample_type'])}",
				"note": _("{0} days late").format(row["days_late"]),
			}
		)
	for entry in data["infrastructure"]["by_category"]:
		out.append(
			{
				"section": _("Infrastructure inspected on time"),
				"item": _(entry["key"]),
				"total": entry["total"],
				"passed": entry["on_time"],
				"pct": _rate(entry["on_time"], entry["total"]),
			}
		)
	wastewater = data.get("wastewater")
	if wastewater:  # FEAT-095 (A-153, FR-M15-12.1): một dòng tóm tắt nước thải
		out.append(
			{
				"section": _("Medical wastewater"),
				"item": _("Monitoring rounds posted (passed = without exceedance)"),
				"total": wastewater["rounds"],
				"passed": wastewater["rounds"] - wastewater["failed"],
				"pct": _rate(wastewater["rounds"] - wastewater["failed"], wastewater["rounds"]),
				"note": _("{0} period(s) overdue or missing parameters").format(wastewater["overdue"]),
			}
		)
	chemicals = data["chemicals"]
	for entry in chemicals["by_department"]:
		out.append(
			{
				"section": _("Surface disinfectant (litres)"),
				"item": entry["label"] or entry["key"],
				"total": round(entry["litres"], 3),
			}
		)
	out.append(
		{
			"section": _("Surface disinfectant (litres)"),
			"item": _("Hospital total"),
			"total": chemicals["litres"],
		}
	)
	return out


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = report_data.build(
		filters.period_type or report_data.MONTH, filters.date or None, filters.department or None
	)
	return columns(), rows(data)
