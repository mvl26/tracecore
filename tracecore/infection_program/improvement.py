"""Dự án cải tiến chất lượng / đề tài nghiên cứu KSNK (FEAT-072; FR-M11-12, FR-M11-12.1; UC-42 bước 5; A-149 Q2, Q4).

- ``status`` theo PDCA: Kế hoạch (P) / Thực hiện (D) / Kiểm tra (C) / Hành động (A) / Hoàn thành / Hủy. Hoàn thành bắt
  buộc ngày kết thúc (không ở tương lai) và tóm tắt kết quả; ngày kết thúc không trước ngày bắt đầu.
- "Số cải tiến/năm" = số dự án Hoàn thành có ngày kết thúc trong năm: hàm chỉ số ``ic_improvement_completed`` (Count,
  từ đầu năm đến hết kỳ; dự án không thuộc khoa nên theo khoa trả 0) và check QĐ 38 cùng tên (chỉ tiêu ``QD38-QI``).
"""

import frappe
from frappe import _
from frappe.utils import cint, get_last_day, getdate, today

DOCTYPE = "IC Improvement Project"
PLAN, DO, CHECK, ACT = "Plan (P)", "Do (D)", "Check (C)", "Act (A)"
COMPLETED, CANCELLED = "Completed", "Cancelled"
STATUSES = (PLAN, DO, CHECK, ACT, COMPLETED, CANCELLED)
IN_PROGRESS = (PLAN, DO, CHECK, ACT)
TYPES = ("Quality Improvement", "Research Project")
INDICATOR_KEY = "ic_improvement_completed"
SELF_CHECK_KEY = "ic_improvement_completed"
MAX_REFS = 5


def validate(doc):
	if doc.start_date and doc.end_date and getdate(doc.end_date) < getdate(doc.start_date):
		frappe.throw(
			_("End date {0} is before start date {1}. Correct the dates.").format(
				frappe.format(doc.end_date, "Date"), frappe.format(doc.start_date, "Date")
			),
			title=_("Project not saved"),
		)
	if doc.status != COMPLETED:
		return
	missing = []
	if not doc.end_date:
		missing.append(_("End Date"))
	if not (doc.result_summary or "").strip():
		missing.append(_("Result Summary"))
	if missing:
		frappe.throw(
			_(
				"A completed project needs {0}. Enter them, or keep the project in an earlier PDCA stage."
			).format(", ".join(missing)),
			title=_("Project not saved"),
		)
	if getdate(doc.end_date) > getdate(today()):
		frappe.throw(
			_("End date {0} is in the future. A project can only be completed on or before today.").format(
				frappe.format(doc.end_date, "Date")
			),
			title=_("Project not saved"),
		)


def _year_bounds(year):
	year = cint(year)
	return getdate(f"{year}-01-01"), getdate(f"{year}-12-31")


def completed(start, end):
	"""Tên dự án Hoàn thành có ngày kết thúc trong [start, end]."""
	return frappe.get_all(
		DOCTYPE,
		filters={"status": COMPLETED, "end_date": ["between", [start, end]]},
		order_by="end_date asc, name asc",
		pluck="name",
	)


def completed_count(period, department=None):
	"""Chỉ số ``ic_improvement_completed`` (FR-M11-12.1): (số dự án Hoàn thành từ đầu năm đến hết kỳ, 0, số đó)."""
	if department:
		return 0, 0, 0
	start = getdate(f"{period}-01")
	count = len(completed(start.replace(month=1, day=1), get_last_day(start)))
	return count, 0, count


def self_check(year):
	"""Check QĐ 38 ``QD38-QI``: năm có ≥ 1 dự án Hoàn thành → Đạt (tham chiếu mã dự án)."""
	names = completed(*_year_bounds(year))
	if not names:
		return {"status": "Not met", "source_ref": ""}
	refs = ", ".join(names[:MAX_REFS]) + ("…" if len(names) > MAX_REFS else "")
	return {"status": "Met", "source_ref": refs}


def rows(year):
	"""Dự án (trừ Hủy) có thời gian giao với năm, kèm số Hoàn thành trong năm và đang làm — cho SCR-49."""
	start, end = _year_bounds(year)
	projects = []
	for row in frappe.get_all(
		DOCTYPE,
		filters={"status": ["!=", CANCELLED], "start_date": ["<=", end]},
		fields=[
			"name",
			"title",
			"project_type",
			"measure_group",
			"lead_name",
			"status",
			"start_date",
			"end_date",
			"result_summary",
		],
		order_by="name asc",
	):
		if row.end_date and getdate(row.end_date) < start:
			continue
		row["status_label"] = _(row.status)
		row["project_type_label"] = _(row.project_type)
		projects.append(row)
	done = sum(
		1
		for row in projects
		if row.status == COMPLETED and row.end_date and start <= getdate(row.end_date) <= end
	)
	doing = sum(1 for row in projects if row.status in IN_PROGRESS)
	return {"projects": projects, "completed": done, "in_progress": doing, "total": len(projects)}


def register_indicators():
	"""Hook ``tracecore_ic_indicators``."""
	return {INDICATOR_KEY: completed_count}


def register_self_checks():
	"""Hook ``tracecore_ic_self_checks`` (QĐ 38 ``QD38-QI``)."""
	return {SELF_CHECK_KEY: self_check}
