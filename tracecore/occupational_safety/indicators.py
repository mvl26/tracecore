"""Chỉ số M16 đẩy sang bảng chỉ số KSNK M9 qua hook `tracecore_ic_indicators` (FEAT-071; FR-M16-09; UC-55 bước 8).

Mỗi hàm nhận kỳ ``YYYY-MM`` và khoa (rỗng = toàn viện), trả (tử số, mẫu số, cỡ mẫu); chỉ số liệu, không có tên.
"""

import frappe
from frappe.utils import get_last_day, getdate

from tracecore.occupational_safety import exposure, immunization


def register():
	return {
		"exposure_report_on_time": report_on_time,
		"exposure_followup_completion": followup_completion,
		"immunization_coverage": immunization_coverage,
	}


def _bounds(period):
	start = getdate(f"{period}-01")
	return start, get_last_day(start)


def _rows(period, department):
	start, end = _bounds(period)
	filters = {
		"status": ["!=", "Cancelled"],
		"occurred_at": ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]],
	}
	if department:
		filters["department"] = department
	return frappe.get_all(
		exposure.DOCTYPE, filters=filters, fields=["name", "status", "report_late", "followup_template"]
	)


def report_on_time(period, department=None):
	rows = _rows(period, department)
	on_time = sum(1 for row in rows if not row.report_late)
	return on_time, len(rows), len(rows)


def followup_completion(period, department=None):
	scheduled = [row for row in _rows(period, department) if row.followup_template]
	done = sum(1 for row in scheduled if row.status == "Completed")
	return done, len(scheduled), len(scheduled)


def immunization_coverage(period, department=None):
	_start, end = _bounds(period)
	result = immunization.coverage(department, day=end)
	return result["fully_covered"], result["at_risk"], result["at_risk"]
