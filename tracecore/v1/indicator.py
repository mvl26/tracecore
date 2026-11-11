"""RPC chỉ đọc tracecore.v1.indicator.* — giá trị chỉ số KSNK đã lưu (FEAT-056; FR-M9-27; NFR-SEC-09, NFR-PERF-05).

Đọc `IC Indicator Value` theo quyền người gọi (`frappe.get_list`): R12 có User Permission Department nên chỉ thấy khoa
mình và dòng toàn viện (khoa trống). Không gọi hàm tính — giá trị đã lưu khi khóa kỳ.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.admin_reports import council_report, ic_board, indicator
from tracecore.admin_reports import self_assessment as self_assessment_service

MAX_PERIODS = 24
INLINE_SAVEPOINT = "tc_indicator_inline"
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
		fields=[
			"indicator",
			"period",
			"value",
			"numerator",
			"denominator",
			"sample_size",
			"sample_note",
			"locked",
		],
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


# --- FEAT-065 (A-145): bảng chỉ số KSNK toàn viện SCR-66 -----------------------------------------------------------


@frappe.whitelist(methods=["GET", "POST"])
def board(year=None, period=None, department=None, chart=None):
	"""Dữ liệu SCR-66 WEB (FR-M9-24, .1, .2; NFR-PERF-05): chỉ đọc `IC Indicator Value`, không tính lại.

	Chỉ R01, R10, R11, R13; R12 xem chỉ số khoa mình trên Cổng khoa (`/ksnk-khoa/chi-so`).
	"""
	return ic_board.board(
		year=year, period=period or None, department=department or None, chart=chart or None
	)


@frappe.whitelist(methods=["GET"])
def council_reports(limit=12):
	"""Báo cáo Hội đồng đã sinh, mới nhất trước (đọc theo DocPerm: R01, R10, R11, R13)."""
	if not frappe.has_permission(council_report.DOCTYPE, "read"):
		frappe.throw(_("You are not allowed to read committee reports."), frappe.PermissionError)
	return frappe.get_list(
		council_report.DOCTYPE,
		fields=["name", "period", "report_status", "generated_on", "pdf"],
		order_by="period desc",
		limit_page_length=min(max(cint(limit), 1), 60),
	)


@frappe.whitelist(methods=["POST"])
def council_generate(period):
	"""R01 sinh lại báo cáo Hội đồng của một kỳ ngay trên SCR-66 (kỳ chưa khóa → bản Tạm)."""
	if frappe.session.user != "Administrator" and council_report.GENERATE_ROLE not in frappe.get_roles():
		frappe.throw(
			_("Only the head of infection control (R01) can generate the committee report."),
			frappe.PermissionError,
		)
	name = council_report.generate(period)
	return frappe.db.get_value(
		council_report.DOCTYPE, name, ["name", "period", "report_status", "generated_on", "pdf"], as_dict=True
	)


# --- FEAT-065 (FR-M9-29, .1): tự đánh giá QĐ 38 trên SCR-66 -------------------------------------------------------


def _inline(fn, *args):
	"""Chạy ``fn``; lỗi nghiệp vụ (ValidationError) → body ``ok: false`` để màn hiện alert-error inline (không modal).

	Lỗi quyền vẫn ném. Hoàn tác về savepoint (không rollback cả request). Thành công trả ``None``.
	"""
	frappe.db.savepoint(INLINE_SAVEPOINT)
	try:
		fn(*args)
	except frappe.PermissionError:
		raise
	except frappe.ValidationError as error:
		frappe.db.rollback(save_point=INLINE_SAVEPOINT)
		frappe.clear_messages()
		return {
			"ok": False,
			"error": {
				"title": _("Not saved"),
				"reason": str(error),
				"action": _("Correct the item above and try again."),
			},
		}
	return None


@frappe.whitelist(methods=["GET"])
def self_assessment(year=None):
	return self_assessment_service.view(year)


@frappe.whitelist(methods=["POST"])
def self_assessment_prepare(year):
	return _inline(self_assessment_service.prepare, year) or self_assessment_service.view(year)


@frappe.whitelist(methods=["POST"])
def self_assessment_set(year, criterion, status, evidence=None, note=None):
	blocked = _inline(self_assessment_service.set_item, year, criterion, status, evidence, note)
	return blocked or self_assessment_service.view(year)


@frappe.whitelist(methods=["POST"])
def self_assessment_submit(year):
	return _inline(self_assessment_service.submit, year) or self_assessment_service.view(year)
