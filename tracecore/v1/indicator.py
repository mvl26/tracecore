"""RPC chỉ đọc tracecore.v1.indicator.* — giá trị chỉ số KSNK đã lưu (FEAT-056; FR-M9-27; NFR-SEC-09, NFR-PERF-05).

Đọc `IC Indicator Value` theo quyền người gọi (`frappe.get_list`): R12 có User Permission Department nên chỉ thấy khoa
mình và dòng toàn viện (khoa trống). Không gọi hàm tính — giá trị đã lưu khi khóa kỳ.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.admin_reports import indicator

MAX_PERIODS = 24
DOCTYPE = indicator.DOCTYPE


def _previous_months(period, count):
	year, month = (int(part) for part in period.split("-"))
	months = []
	for _step in range(count):
		months.append(f"{year:04d}-{month:02d}")
		month -= 1
		if month == 0:
			year, month = year - 1, 12
	return list(reversed(months))


def _latest_period(department):
	rows = frappe.get_list(
		DOCTYPE,
		filters={"department": department or ("is", "not set")},
		fields=["period"],
		order_by="period desc",
		limit_page_length=1,
	)
	return rows[0].period if rows else None


@frappe.whitelist(methods=["GET", "POST"])
def values(period=None, department=None, periods=3):
	"""Giá trị đã lưu của mọi chỉ số đang dùng cho ``periods`` tháng tính lùi từ ``period`` (mặc định: kỳ mới nhất).

	``department`` trống = toàn viện. Trả ``{"periods": [...], "department": ..., "rows": [...]}``; mỗi giá trị có
	``value`` (``None`` khi "Không tính"), ``status`` bằng chữ (Met / Not met / Not calculated / Insufficient sample).
	"""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("You are not allowed to read infection control indicators."), frappe.PermissionError)
	department = department or None
	count = min(max(cint(periods) or 1, 1), MAX_PERIODS)
	period = period or _latest_period(department)
	if period:
		indicator.check_period(period)
	months = _previous_months(period, count) if period else []
	stored = frappe.get_list(
		DOCTYPE,
		filters={
			"period": ("in", months or [""]),
			"department": department or ("is", "not set"),
		},
		fields=["indicator", "period", "value", "numerator", "denominator", "sample_size", "sample_note", "locked"],
		limit_page_length=0,
	)
	by_indicator = {}
	for row in stored:
		by_indicator.setdefault(row.indicator, {})[row.period] = row
	result = []
	for ind in frappe.get_all(
		"IC Indicator",
		filters={"is_active": 1},
		fields=[
			"name",
			"indicator_name",
			"measure_group",
			"kind",
			"national_target",
			"target_direction",
			"target_ref",
			"min_sample",
		],
		order_by="measure_group asc, name asc",
	):
		values_ = {
			p: {
				"value": indicator.display_value(r),
				"numerator": r.numerator,
				"denominator": r.denominator,
				"sample_size": r.sample_size,
				"sample_note": r.sample_note or "",
				"locked": cint(r.locked),
				"status": indicator.status(r, ind),
			}
			for p, r in by_indicator.get(ind.name, {}).items()
		}
		result.append(
			{
				"code": ind.name,
				"indicator_name": ind.indicator_name,
				"measure_group": ind.measure_group,
				"kind": ind.kind,
				"national_target": ind.national_target if ind.target_direction else None,
				"target_direction": ind.target_direction or "",
				"target_ref": ind.target_ref or "",
				"values": values_,
			}
		)
	return {"periods": months, "department": department, "rows": result}
