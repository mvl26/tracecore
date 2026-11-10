"""Bảng chỉ số KSNK toàn viện và Cổng khoa (FEAT-065; FR-M9-24, FR-M9-24.1, FR-M9-24.2, FR-M9-26, FR-M9-26.1;
BRU-RPT-001, BRU-RPT-003; NFR-PERF-05; UC-57 bước 3, 5; A-145 Q3, Q4, D1-D4, D7).

Chỉ **đọc** `IC Indicator Value` đã lưu (kỳ đã khóa, hoặc dòng tạm của kỳ chưa khóa mang nhãn "Tạm"); không gọi hàm tính
của module (``core.indicators.registry``) khi mở bảng. Danh sách chỉ số và mục tiêu lấy từ `IC Plan Indicator` của kế hoạch
năm đã ghi sổ; năm chưa có kế hoạch thì lấy mọi `IC Indicator` đang dùng với chỉ tiêu quốc gia.

Việc cần xử lý gom qua hook ``tracecore_ksnk_todos``: mỗi hàm nhận ``(user, department)`` (``department`` trống = toàn
viện) và trả danh sách ``{key, severity, title, count, detail, link}``; M9 không import module nghiệp vụ.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from tracecore.admin_reports import indicator

VALUE = indicator.DOCTYPE
PLAN = "IC Annual Plan"
TODO_HOOK = "tracecore_ksnk_todos"
TREND_MONTHS = 12
TABLE_MONTHS = 3
KPI_COUNT = 8
HAND_HYGIENE = "Hand Hygiene"
NO_DATA = "No data"
SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
BOARD_ROLES = ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager")
PORTAL_ROLES = ("TC R01", "TC R08", "TC R11", "TC R12", "System Manager")
DEPT_ROLES = ("TC R08", "TC R12")


# --- kỳ ----------------------------------------------------------------------------------------------------------


def previous_months(period, count):
	"""``count`` tháng ``YYYY-MM`` liên tiếp kết thúc ở ``period`` (tăng dần)."""
	year, month = (int(part) for part in period.split("-"))
	months = []
	for _step in range(count):
		months.append(f"{year:04d}-{month:02d}")
		month -= 1
		if month == 0:
			year, month = year - 1, 12
	return list(reversed(months))


def latest_period(year=None):
	"""Kỳ mới nhất có giá trị toàn viện (trong ``year`` nếu có)."""
	filters = {"department": ("is", "not set")}
	if year:
		filters["period"] = ("like", f"{cint(year):04d}-%")
	rows = frappe.get_all(
		VALUE, filters=filters, fields=["period"], order_by="period desc", limit_page_length=1
	)
	return rows[0].period if rows else None


# --- chỉ số của kế hoạch -----------------------------------------------------------------------------------------


def approved_plan(year):
	return frappe.db.get_value(PLAN, {"year": cint(year), "docstatus": 1}, ["name", "year"], as_dict=True)


def plan_indicators(year):
	"""(kế hoạch hoặc None, [chỉ số theo thứ tự kế hoạch]) — mục tiêu của kế hoạch, thiếu (0) thì chỉ tiêu quốc gia."""
	plan = approved_plan(year)
	fields = [
		"name",
		"indicator_name",
		"measure_group",
		"kind",
		"national_target",
		"target_direction",
		"target_ref",
		"min_sample",
	]
	if plan:
		lines = frappe.get_all(
			"IC Plan Indicator",
			filters={"parent": plan.name, "parenttype": PLAN},
			fields=["indicator", "indicator_name", "target"],
			order_by="idx asc",
		)
		catalog = {
			row.name: row
			for row in frappe.get_all(
				"IC Indicator",
				filters={"name": ("in", [line.indicator for line in lines] or [""])},
				fields=fields,
			)
		}
		result = []
		for line in lines:
			ind = catalog.get(line.indicator)
			if not ind:
				continue
			target = flt(line.target) if flt(line.target) else ind.national_target
			result.append(_meta(ind, target, line.indicator_name))
		return plan, result
	rows = frappe.get_all(
		"IC Indicator", filters={"is_active": 1}, fields=fields, order_by="measure_group asc, name asc"
	)
	return None, [_meta(ind, ind.national_target) for ind in rows]


def _meta(ind, target, name=None):
	direction = ind.target_direction or ""
	return frappe._dict(
		code=ind.name,
		indicator_name=name or ind.indicator_name or ind.name,
		measure_group=ind.measure_group or "",
		kind=ind.kind,
		target=flt(target) if direction else None,
		target_direction=direction,
		target_ref=ind.target_ref or "",
		min_sample=cint(ind.min_sample),
	)


def cell(row, meta):
	"""Một ô giá trị đã lưu: giá trị hiển thị (``None`` = "Không tính"), trạng thái bằng chữ, cờ Tạm."""
	if not row:
		return None
	return {
		"value": indicator.display_value(row),
		"numerator": flt(row.numerator),
		"denominator": flt(row.denominator),
		"sample_size": cint(row.sample_size),
		"sample_note": row.sample_note or "",
		"locked": cint(row.locked),
		"status": indicator.status(
			row, {"target_direction": meta.target_direction, "national_target": meta.target}
		),
	}


def _stored(codes, periods, departments):
	"""{(chỉ số, kỳ, khoa hoặc None): dòng} — một truy vấn."""
	if not codes or not periods:
		return {}
	filters = {"indicator": ("in", codes), "period": ("in", periods)}
	named = [d for d in departments if d]
	if None in departments and not named:
		filters["department"] = ("is", "not set")
	elif named and None not in departments:
		filters["department"] = ("in", named)
	rows = frappe.get_all(
		VALUE,
		filters=filters,
		fields=[
			"indicator",
			"period",
			"department",
			"value",
			"numerator",
			"denominator",
			"sample_size",
			"sample_note",
			"locked",
		],
		limit_page_length=0,
	)
	if None in departments and named:
		wanted = set(named)
		rows = [row for row in rows if not row.department or row.department in wanted]
	return {(row.indicator, row.period, row.department or None): row for row in rows}


# --- việc cần xử lý ----------------------------------------------------------------------------------------------


def _todo_paths():
	"""Hàm đã đăng ký cho hook ``tracecore_ksnk_todos`` theo thứ tự trong ``hooks.py``."""
	return [frappe.get_attr(path) for path in frappe.get_hooks(TODO_HOOK) or []]


def todos(user=None, department=None):
	"""Việc cần xử lý từ mọi module (hook ``tracecore_ksnk_todos``), việc nặng trước; bỏ việc đếm 0.

	Một hàm hook lỗi không làm hỏng cả bảng: ghi Error Log và bỏ qua phần của module đó.
	"""
	user = user or frappe.session.user
	items = []
	for fn in _todo_paths():
		name = getattr(fn, "__module__", "") + "." + getattr(fn, "__name__", "")
		try:
			result = fn(user, department or None)
		except Exception:
			frappe.log_error(title=f"TraceCore KSNK todo hook failed: {name}")
			continue
		for item in result or []:
			if not item or cint(item.get("count")) <= 0:
				continue
			items.append(
				{
					"key": item.get("key") or name,
					"severity": item.get("severity") if item.get("severity") in SEVERITY_ORDER else "info",
					"title": item.get("title") or "",
					"count": cint(item.get("count")),
					"detail": item.get("detail") or "",
					"link": item.get("link") or "",
				}
			)
	items.sort(key=lambda item: SEVERITY_ORDER[item["severity"]])
	return items


# --- quyền -------------------------------------------------------------------------------------------------------


def _roles(user):
	return set(frappe.get_roles(user))


def require_board(user=None):
	"""FR-M9-24.2: bảng toàn viện chỉ cho R01, R10, R11, R13 (R12 dùng Cổng khoa)."""
	user = user or frappe.session.user
	if user == "Administrator" or _roles(user) & set(BOARD_ROLES):
		return
	frappe.throw(
		_("You are not allowed to open the hospital infection control board."), frappe.PermissionError
	)


def portal_departments(user=None):
	"""Khoa người dùng được xem trên Cổng khoa: R08/R12 theo User Permission; R01, R11 mọi khoa lâm sàng."""
	user = user or frappe.session.user
	roles = _roles(user)
	if user != "Administrator" and not roles & set(PORTAL_ROLES):
		frappe.throw(_("You are not allowed to open the department portal."), frappe.PermissionError)
	wide = user == "Administrator" or roles & (set(PORTAL_ROLES) - set(DEPT_ROLES))
	filters = {"disabled": 0, "is_group": 0}
	if wide:
		filters["tc_is_ward"] = 1
	else:
		allowed = frappe.get_all(
			"User Permission", filters={"user": user, "allow": "Department"}, pluck="for_value"
		)
		filters["name"] = ("in", allowed or [""])
	rows = frappe.get_all(
		"Department", filters=filters, fields=["name", "department_name"], order_by="department_name asc"
	)
	return [{"name": row.name, "label": row.department_name or row.name} for row in rows]


# --- bảng toàn viện ----------------------------------------------------------------------------------------------


def _department_chart(metas, period, chart_code=None):
	"""Giá trị theo khoa của một chỉ số ở kỳ ``period`` (D4): mặc định chỉ số Vệ sinh tay đầu tiên có số liệu khoa."""
	if not period or not metas:
		return None
	codes = [meta.code for meta in metas]
	rows = frappe.get_all(
		VALUE,
		filters={"indicator": ("in", codes), "period": period, "department": ("is", "set")},
		fields=["indicator", "department", "value", "sample_note", "locked", "numerator", "denominator"],
		limit_page_length=0,
	)
	by_code = {}
	for row in rows:
		by_code.setdefault(row.indicator, []).append(row)
	with_data = [meta for meta in metas if meta.code in by_code]
	if not with_data:
		return None
	chosen = next((meta for meta in with_data if meta.code == chart_code), None)
	chosen = (
		chosen
		or next((meta for meta in with_data if meta.measure_group == HAND_HYGIENE), None)
		or with_data[0]
	)
	names = dict(
		frappe.get_all(
			"Department",
			filters={"name": ("in", [row.department for row in by_code[chosen.code]])},
			fields=["name", "department_name"],
			as_list=True,
		)
	)
	bars = []
	for row in by_code[chosen.code]:
		data = cell(row, chosen)
		bars.append(
			{
				"department": row.department,
				"department_name": names.get(row.department) or row.department,
				**data,
			}
		)
	bars.sort(key=lambda bar: (bar["value"] is None, -(bar["value"] or 0)))
	return {
		"indicator": chosen.code,
		"indicator_name": chosen.indicator_name,
		"kind": chosen.kind,
		"target": chosen.target,
		"target_direction": chosen.target_direction,
		"period": period,
		"options": [{"code": meta.code, "indicator_name": meta.indicator_name} for meta in with_data],
		"rows": bars,
	}


def latest_council_report():
	rows = frappe.get_all(
		"IC Council Report",
		fields=["name", "period", "report_status", "generated_on", "pdf"],
		order_by="period desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def board(year=None, period=None, department=None, chart=None, user=None):
	"""Dữ liệu SCR-66 WEB: chỉ số kế hoạch năm, 12 kỳ, KPI, biểu đồ theo khoa, việc cần xử lý, báo cáo Hội đồng."""
	user = user or frappe.session.user
	require_board(user)
	department = department or None
	if period:
		indicator.check_period(period)
	year = cint(year) or (cint(period[:4]) if period else 0)
	if not period:
		period = latest_period(year or None)
	year = year or (cint(period[:4]) if period else getdate(today()).year)
	plan, metas = plan_indicators(year)
	periods = previous_months(period, TREND_MONTHS) if period else []
	stored = _stored([meta.code for meta in metas], periods, [department])
	rows = []
	for meta in metas:
		values = {}
		for p in periods:
			data = cell(stored.get((meta.code, p, department)), meta)
			if data:
				values[p] = data
		latest = values.get(period) if period else None
		rows.append(
			{
				**meta,
				"values": values,
				"latest": latest,
				"status": latest["status"] if latest else NO_DATA,
			}
		)
	locked = bool(period) and indicator.is_locked(period)
	return {
		"year": year,
		"plan": {"name": plan.name} if plan else None,
		"period": period,
		"periods": periods,
		"table_periods": periods[-TABLE_MONTHS:],
		"locked": locked,
		"department": department,
		"rows": rows,
		"kpis": [row["code"] for row in rows[:KPI_COUNT]],
		"chart": None if department else _department_chart(metas, period, chart),
		"todos": todos(user, department),
		"council_report": latest_council_report(),
	}


# --- Cổng khoa ---------------------------------------------------------------------------------------------------


def department_view(department=None, user=None):
	"""Dữ liệu Cổng khoa (FR-M9-26): chỉ số kỳ gần nhất của khoa cạnh toàn viện + việc cần làm của khoa.

	R08/R12 chỉ khoa có User Permission; yêu cầu khoa khác → PermissionError (FR-M9-26.1, UC-57 E3).
	"""
	user = user or frappe.session.user
	departments = portal_departments(user)
	names = [row["name"] for row in departments]
	if department and department not in names:
		frappe.throw(_("You cannot see the indicators of this department."), frappe.PermissionError)
	department = department or (names[0] if names else None)
	result = {"departments": departments, "department": department, "period": None, "rows": [], "todos": []}
	if not department:
		return result
	period = latest_period()
	year = cint(period[:4]) if period else getdate(today()).year
	_plan, metas = plan_indicators(year)
	stored = _stored([meta.code for meta in metas], [period] if period else [], [None, department])
	rows = []
	for meta in metas:
		own = cell(stored.get((meta.code, period, department)), meta)
		whole = cell(stored.get((meta.code, period, None)), meta)
		if not own and not whole:
			continue
		rows.append(
			{
				**meta,
				"department_value": own,
				"hospital_value": whole,
				"status": own["status"] if own else NO_DATA,
			}
		)
	result.update(
		{
			"period": period,
			"locked": bool(period) and indicator.is_locked(period),
			"rows": rows,
			"todos": todos(user, department),
		}
	)
	return result
