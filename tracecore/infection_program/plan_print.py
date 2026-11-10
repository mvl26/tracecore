"""Ngữ cảnh in "Kế hoạch KSNK năm" và "Báo cáo tổng kết KSNK" (FEAT-058; FR-M11-04, FR-M11-06, FR-M11-06.2).

Một hàm duy nhất trong ``jinja.methods`` (không đưa cả module vào môi trường Jinja). Ngày ``dd/mm/yyyy``, VND không
lẻ có dấu chấm nghìn, số đo dấu phẩy thập phân; chỉ người đọc được kế hoạch mới in được.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, get_datetime

from tracecore.core.print_tokens import token_values
from tracecore.infection_program import annual_plan, reminders

UNIT = {"Percentage": " %", "Rate per 1000": " ‰"}
STATUS_TEXT = {
	"completed": "Completed",
	"overdue": "Overdue",
	"due_soon": "Due soon",
	"in_progress": "In Progress",
	"planned": "Planned",
}


def vnd(value):
	return f"{cint(round(flt(value))):,}".replace(",", ".")


def number(value, kind=None):
	if value is None:
		return ""
	text = f"{flt(value, 1):,.1f}".replace(",", " ").replace(".", ",").replace(" ", ".")
	if text.endswith(",0"):
		text = text[:-2]
	return text + UNIT.get(kind, "")


def date(value):
	return formatdate(value, "dd/mm/yyyy") if value else ""


def _self_assessment(row):
	"""FEAT-072: "<điểm> % · <kết quả> · <ngày> (<mã phiếu>)" hoặc "—"."""
	if not row:
		return "—"
	parts = [number(row.score_pct, "Percentage") if row.score_pct is not None else _("not scored")]
	if row.result_label:
		parts.append(row.result_label)
	parts.append(f"{date(row.audit_date)} ({row.name})")
	return " · ".join(parts)


def tc_ic_plan_context(name: str) -> dict:
	doc = frappe.get_doc(annual_plan.DOCTYPE, name)
	doc.check_permission("read")
	summary = annual_plan.year_summary(name)
	approved_on = get_datetime(doc.approved_on).strftime("%d/%m/%Y %H:%M") if doc.approved_on else ""
	return {
		"tc": token_values(),
		"name": doc.name,
		"year": cint(doc.year),
		"draft": doc.docstatus == 0,
		"cancelled": doc.docstatus == 2,
		"provisional": summary["provisional"],
		"objectives": doc.objectives or "",
		"approved_by": summary["approved_by"],
		"approved_on": approved_on,
		"total_budget": vnd(doc.total_budget_vnd),
		"summary": doc.summary or "",
		"progress": _("{0}/{1} completed").format(
			summary["activities_completed"], summary["activities_total"]
		),
		# FEAT-072 (A-149): số dự án cải tiến hoàn thành, kết quả tự đánh giá chất lượng của năm
		"improvement_completed": str(summary["improvement_completed"]),
		"self_assessment": _self_assessment(summary["self_assessment"]),
		"indicators": [
			{
				"name": row["indicator_name"],
				"baseline": number(row["baseline"], row["kind"]),
				"target": (
					"≥ " if row["direction"] == "Higher is better" else "≤ " if row["direction"] else ""
				)
				+ number(row["target"], row["kind"]),
				"value": number(row["value"], row["kind"]) if row["value"] is not None else "—",
				"status": row["status_label"],
			}
			for row in summary["indicators"]
		],
		"activities": [
			{
				"index": row.idx,
				"activity": row.activity,
				"measure_group": _(row.measure_group) if row.measure_group else "",
				"responsible": row.responsible_name or row.responsible,
				"department": row.department_name or row.department or "",
				"due_date": date(row.due_date),
				"budget": vnd(row.budget_vnd),
				"status": _(
					STATUS_TEXT[reminders.display_status(row.status, row.due_date)], context="IC Plan"
				),
				"evidence": row.evidence or "",
			}
			for row in doc.activities
		],
	}
