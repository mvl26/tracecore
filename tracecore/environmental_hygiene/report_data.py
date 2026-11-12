"""Báo cáo môi trường tháng/quý (FEAT-070; FR-M15-07, .1; UC-54 bước 8).

Gộp giám sát vệ sinh (phiếu VSMT gắn vùng), xét nghiệm môi trường, kiểm tra hạ tầng và lít hóa chất khử khuẩn bề mặt.
Hóa chất đọc `IC Chemical Consumption` đã ghi sổ theo ``period`` (YYYY-MM) và ``chemical_type`` — cùng nguồn, cùng điều
kiện với báo cáo quý M12 (``compliance_audit.chemicals.monthly``) nên số liệu khớp (FR-M15-07.1); M15 không import M12.
"""

import frappe
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, today

from tracecore.environmental_hygiene import audits, plans, wastewater_report, zones

MONTH, QUARTER = "Month", "Quarter"
CHEMICAL_DOCTYPE = "IC Chemical Consumption"
SURFACE_DISINFECTANT = "Surface Disinfectant"


def bounds(period_type, on=None):
	on = getdate(on or today())
	if period_type == QUARTER:
		start = getdate(f"{on.year}-{(on.month - 1) // 3 * 3 + 1:02d}-01")
		return start, get_last_day(add_months(start, 2))
	return get_first_day(on), get_last_day(on)


def _months(start, end):
	months, cursor = [], getdate(start)
	while cursor <= getdate(end):
		months.append(cursor.strftime("%Y-%m"))
		cursor = add_months(cursor, 1)
	return months


def samples_summary(start, end, department=None):
	filters = {"docstatus": 1, "sampled_on": ["between", [start, end]]}
	if department:
		filters["department"] = department
	rows = frappe.get_all(
		"Environmental Sample",
		filters=filters,
		fields=[
			"name",
			"environment_zone",
			"environment_zone_name",
			"department",
			"sample_type",
			"sampled_on",
			"result_value",
			"unit",
			"limit_applied",
			"result",
			"is_resample_of",
			"nc_status",
			"nc_name",
		],
		order_by="sampled_on desc, creation desc",
	)
	by_type = {}
	for row in rows:
		entry = by_type.setdefault(row.sample_type, {"key": row.sample_type, "total": 0, "failed": 0})
		entry["total"] += 1
		entry["failed"] += 1 if row.result == "Fail" else 0
	return {
		"total": len(rows),
		"failed": sum(1 for row in rows if row.result == "Fail"),
		"by_type": sorted(by_type.values(), key=lambda entry: entry["key"]),
		"rows": rows,
	}


def chemicals(start, end, department=None):
	months = _months(start, end)
	filters = {
		"docstatus": 1,
		"period": ["in", months],
		"chemical_type": SURFACE_DISINFECTANT,
	}
	if department:
		filters["department"] = department
	rows = frappe.get_all(
		CHEMICAL_DOCTYPE, filters=filters, fields=["department", "department_name", "qty_litre"]
	)
	by_department = {}
	for row in rows:
		entry = by_department.setdefault(
			row.department, {"key": row.department, "label": row.department_name, "litres": 0.0}
		)
		entry["litres"] += flt(row.qty_litre)
	return {
		"litres": round(sum(flt(row.qty_litre) for row in rows), 3),
		"by_department": sorted(by_department.values(), key=lambda entry: entry["label"] or ""),
	}


def build(period_type=MONTH, on=None, department=None):
	"""Số liệu báo cáo môi trường của tháng/quý chứa ``on``."""
	start, end = bounds(period_type, on)
	systems = audits.infra_systems(end, department)
	categories = {}
	for row in systems:
		entry = categories.setdefault(
			row["infra_category"] or "Other",
			{"key": row["infra_category"] or "Other", "total": 0, "on_time": 0},
		)
		entry["total"] += 1
		entry["on_time"] += 0 if row["status"] == audits.OVERDUE else 1
	return {
		"period_type": period_type,
		"from_date": start,
		"to_date": end,
		"hygiene": audits.pass_rates(start, end, department),
		"high_risk": audits.high_risk_pass(start, end, department),
		"coverage": zones.short_zones(end, department),
		"samples": samples_summary(start, end, department),
		"overdue_samples": plans.overdue(min(getdate(end), getdate(today()))),
		"infrastructure": {
			"rows": systems,
			"by_category": sorted(categories.values(), key=lambda e: e["key"]),
		},
		"chemicals": chemicals(start, end, department),
		# FEAT-095 (A-153, FR-M15-12.1): nước thải là toàn viện, không lọc theo khoa
		"wastewater": None if department else wastewater_report.brief(start, end),
	}
