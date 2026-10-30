"""Sổ tiệt khuẩn điện tử, báo cáo KSNK, dự báo hết vòng đời (M9, FEAT-007; FR-M9-02, FR-M9-02.1, OTH-LEG-001; A-57).

Chỉ đọc, truy vấn DocType theo tên (M9 không import M1/M2). Ba Script Report gọi `log_rows`, `ksnk_summary`,
`life_forecast`; `render_html` dựng bản in (người xuất, thời điểm xuất, chỗ ký Trưởng khoa KSNK, dấu TẠM khi kỳ chưa
khóa); `build_export` là job RQ ``long`` sinh PDF, lưu File riêng tư và báo người xuất (NFR-PERF-03). Ngày khóa báo cáo ở
`TraceCore Settings.report_locked_until`, chỉ R01 đặt qua `lock_period` (Audit Log).
"""

import math
import re

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	add_months,
	cint,
	escape_html,
	flt,
	get_datetime,
	get_fullname,
	getdate,
	now_datetime,
)

from tracecore.core import audit, print_tokens

LOAD = "Sterilization Load"
RUNNING, RELEASED, FAILED = "Running", "Released", "Failed"
INACTIVE_SET_STATUSES = ("Disposed", "Returned")
END_OF_LIFE = "End of Life"
RATE_DAYS = 90  # tốc độ dùng = số mẻ giải phóng trong 90 ngày ÷ 3 tháng (A-57 Q4)
RATE_MONTHS = 3
HORIZON_MONTHS = 12
SETTINGS = "TraceCore Settings"
TEMPLATE_PATH = ("admin_reports", "print", "tc_report.html")
DATE_FORMAT = "%d/%m/%Y"
DATETIME_FORMAT = "%d/%m/%Y %H:%M"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# loại báo cáo → Script Report (quyền xuất theo quyền Report), tiêu đề, khổ giấy
KINDS = {
	"sterilization_log": {
		"report": "Sterilization Log",
		"title": "Electronic Sterilization Log",
		"landscape": True,
	},
	"ksnk_summary": {
		"report": "KSNK Summary Report",
		"title": "Infection Control Summary Report",
		"landscape": False,
	},
	"life_forecast": {
		"report": "Instrument Life Forecast",
		"title": "Set End-of-Life Forecast",
		"landscape": True,
	},
}
INDICATORS = {
	"bowie_dick": "Bowie-Dick",
	"chemical_class_5": "Chemical Class 5",
	"chemical_plasma": "Chemical (Plasma)",
	"biological": "Biological",
}


# --- kỳ và khóa kỳ ---------------------------------------------------------------------------------------------


def period(filters):
	"""``(từ ngày, đến ngày)`` của bộ lọc; thiếu hoặc ngược → ValidationError."""
	filters = frappe._dict(filters or {})
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Choose the period (from date and to date)."))
	start, end = getdate(filters.from_date), getdate(filters.to_date)
	if start > end:
		frappe.throw(_("The from date is after the to date."))
	return start, end


def is_locked(to_date):
	"""Kỳ kết thúc ``to_date`` đã khóa (≤ ngày khóa báo cáo); chưa khóa thì bản xuất có dấu TẠM (FR-M9-02.1)."""
	locked = frappe.db.get_single_value(SETTINGS, "report_locked_until")
	return bool(locked) and getdate(to_date) <= getdate(locked)


def lock_period(until):
	"""Đặt ngày khóa báo cáo (quyền R01 kiểm ở RPC); ghi Audit Log old/new."""
	if not isinstance(until, str) or not _ISO_DATE.match(until):
		frappe.throw(_("The lock date must be a date (YYYY-MM-DD)."))
	until = getdate(until)
	old = frappe.db.get_single_value(SETTINGS, "report_locked_until")
	frappe.db.set_single_value(SETTINGS, "report_locked_until", until)
	audit.log(
		"Update",
		SETTINGS,
		SETTINGS,
		old={"report_locked_until": str(old) if old else None},
		new={"report_locked_until": str(until)},
	)
	return until


# --- sổ tiệt khuẩn (Q1) ---------------------------------------------------------------------------------------


def _loads(filters, fields):
	start, end = period(filters)
	conditions = [
		["status", "!=", RUNNING],
		["started_at", ">=", start],
		["started_at", "<", add_days(end, 1)],
	]
	if filters.get("equipment"):
		conditions.append(["equipment", "=", filters["equipment"]])
	if filters.get("department"):
		names = frappe.db.sql_list(
			"""select distinct lp.parent from `tabLoad Pack` lp join `tabPack` p on p.name = lp.pack
			where lp.parenttype = %s and p.department = %s""",
			(LOAD, filters["department"]),
		)
		conditions.append(["name", "in", names or [""]])
	return frappe.get_all(LOAD, filters=conditions, fields=fields, order_by="started_at asc, name asc")


def _names(doctype, names, field):
	names = [name for name in set(names) if name]
	if not names:
		return {}
	return dict(
		frappe.get_all(doctype, filters={"name": ["in", names]}, fields=["name", field], as_list=True)
	)


def _params_text(raw):
	try:
		params = frappe.parse_json(raw) if raw else []
	except Exception:
		params = []
	parts = []
	for row in params if isinstance(params, list) else []:
		if not isinstance(row, dict):
			continue
		value = row.get("value")
		text = f"{row.get('parameter_name') or ''} {'' if value is None else value} {row.get('unit') or ''}".strip()
		parts.append(text + (" (!)" if cint(row.get("outside_range")) else ""))
	return "; ".join(parts)


def log_rows(filters):
	"""Mỗi mẻ của kỳ (trừ mẻ Đang chạy) một dòng: thông số, chỉ thị, gói/bộ, người vận hành, người giải phóng."""
	filters = frappe._dict(filters or {})
	loads = _loads(
		filters,
		[
			"name",
			"equipment",
			"program",
			"operator",
			"status",
			"started_at",
			"ended_at",
			"params",
			"released_by",
			"released_at",
		],
	)
	names = [load.name for load in loads]
	packs, indicators = {}, {}
	if names:
		for row in frappe.get_all(
			"Load Pack",
			filters={"parent": ["in", names], "parenttype": LOAD},
			fields=["parent", "set_unit"],
			order_by="idx asc",
		):
			packs.setdefault(row.parent, []).append(row.set_unit)
		for row in frappe.get_all(
			"Load Indicator Result",
			filters={"load": ["in", names]},
			fields=["load", "indicator", "result", "lot"],
			order_by="creation asc",
		):
			indicators.setdefault(row.load, []).append(row)
	set_ids = _names("Set Unit", [unit for units in packs.values() for unit in units], "set_id")
	equipment = _names("Equipment", [load.equipment for load in loads], "equipment_name")
	programs = _names("Process Program", [load.program for load in loads], "program_name")
	people = _names(
		"Employee", [p for load in loads for p in (load.operator, load.released_by)], "employee_name"
	)
	rows = []
	for load in loads:
		rows.append(
			{
				"date": getdate(load.started_at),
				"load": load.name,
				"equipment": load.equipment,
				"equipment_name": equipment.get(load.equipment) or load.equipment,
				"program": load.program,
				"program_name": programs.get(load.program) or load.program,
				"started_at": load.started_at,
				"ended_at": load.ended_at,
				"params": _params_text(load.params),
				"indicators": "; ".join(
					f"{_(INDICATORS.get(row.indicator, row.indicator))}: {_(row.result)}"
					+ (f" ({row.lot})" if row.lot else "")
					for row in indicators.get(load.name, [])
				),
				"pack_count": len(packs.get(load.name, [])),
				"sets": ", ".join(set_ids.get(unit) or unit for unit in packs.get(load.name, [])),
				"operator": load.operator,
				"operator_name": people.get(load.operator) or load.operator,
				"released_by": load.released_by,
				"released_by_name": people.get(load.released_by) or load.released_by,
				"released_at": load.released_at,
				"result": load.status,
			}
		)
	return rows


# --- báo cáo KSNK tổng hợp (Q2) -----------------------------------------------------------------------------------


def _rate(failed, passed):
	return round(failed * 100 / (failed + passed), 1) if failed + passed else 0


def ksnk_summary(filters):
	"""Tổng hợp kỳ: mẻ theo máy, chỉ thị sinh học, lô rửa, gói, cấp phát theo khoa, thu hồi, sự cố theo loại."""
	filters = frappe._dict(filters or {})
	start, end = period(filters)
	after_end = add_days(end, 1)
	loads = _loads(filters, ["name", "equipment", "status"])
	machines = {}
	for load in loads:
		row = machines.setdefault(
			load.equipment, {"equipment": load.equipment, "loads": 0, "passed": 0, "failed": 0}
		)
		row["loads"] += 1
		row["passed"] += load.status == RELEASED
		row["failed"] += load.status == FAILED
	info = {
		row.name: row
		for row in frappe.get_all(
			"Equipment",
			filters={"name": ["in", list(machines) or [""]]},
			fields=["name", "equipment_name", "equipment_type"],
		)
	}
	for name, row in machines.items():
		row["equipment_name"] = info[name].equipment_name if name in info else name
		row["equipment_type"] = info[name].equipment_type if name in info else None
		row["fail_rate"] = _rate(row["failed"], row["passed"])
	names = [load.name for load in loads] or [""]
	released = [load.name for load in loads if load.status == RELEASED] or [""]
	bi = frappe.get_all(
		"Load Indicator Result",
		filters={"load": ["in", names], "indicator": "biological", "result": ["in", ["Pass", "Fail"]]},
		pluck="result",
	)
	wash = frappe.get_all(
		"Wash Batch",
		filters=[["started_at", ">=", start], ["started_at", "<", after_end], ["status", "!=", RUNNING]],
		pluck="status",
	)
	issue_filters = [["docstatus", "=", 1], ["issued_at", ">=", start], ["issued_at", "<", after_end]]
	if filters.get("department"):
		issue_filters.append(["department", "=", filters.department])
	issued = {}
	for row in frappe.get_all("Issue Note", filters=issue_filters, fields=["department", "pack_count"]):
		issued[row.department] = issued.get(row.department, 0) + cint(row.pack_count)
	incidents = {}
	for kind in frappe.get_all(
		"Incident CAPA",
		filters=[
			["occurred_at", ">=", start],
			["occurred_at", "<", after_end],
			["status", "!=", "Cancelled"],
		],
		pluck="incident_type",
	):
		incidents[kind] = incidents.get(kind, 0) + 1
	return {
		"from_date": start,
		"to_date": end,
		"equipment": sorted(machines.values(), key=lambda row: row["equipment"]),
		"biological": {"tests": len(bi), "positive": bi.count("Fail")},
		"packs_sterilized": frappe.db.count("Load Pack", {"parent": ["in", released], "parenttype": LOAD}),
		"wash": {"batches": len(wash), "passed": wash.count("Passed"), "failed": wash.count("Failed")},
		"issued": [{"department": dept, "packs": count} for dept, count in sorted(issued.items())],
		"recalls": frappe.db.count(
			"Recall Order",
			[["opened_at", ">=", start], ["opened_at", "<", after_end], ["docstatus", "!=", 2]],
		),
		"incidents": [{"incident_type": kind, "count": count} for kind, count in sorted(incidents.items())],
	}


# --- dự báo hết vòng đời (Q4) --------------------------------------------------------------------------------------


def _uses_since(since):
	return dict(
		frappe.db.sql(
			"""select lp.set_unit, count(distinct l.name) from `tabLoad Pack` lp
			join `tabSterilization Load` l on l.name = lp.parent
			where lp.parenttype = %s and l.status = %s
				and coalesce(l.released_at, l.ended_at, l.started_at) >= %s
			group by lp.set_unit""",
			(LOAD, RELEASED, since),
		)
	)


def _bom_price(set_type, version, cache):
	key = (set_type, version)
	if key not in cache:
		cache[key] = flt(
			frappe.db.sql(
				"""select sum(b.qty * coalesce(i.value, 0)) from `tabSet BOM Item` b
				join `tabInstrument` i on i.name = b.instrument
				where b.set_type = %s and b.bom_version = %s""",
				(set_type, version),
			)[0][0]
		)
	return cache[key]


def life_forecast(filters=None, on=None):
	"""Bộ dự kiến hết cơ số trong 12 tháng tới: tháng hết, chu trình còn lại, tốc độ/tháng, giá thay theo BOM."""
	filters = frappe._dict(filters or {})
	day = getdate(on or now_datetime())
	conditions = {"status": ["not in", INACTIVE_SET_STATUSES], "is_loaner": 0, "max_cycles": [">", 0]}
	if filters.get("department"):
		conditions["department"] = filters.department
	units = frappe.get_all(
		"Set Unit",
		filters=conditions,
		fields=[
			"name",
			"set_id",
			"set_type",
			"department",
			"status",
			"cycles_used",
			"max_cycles",
			"cycle_bom_version",
		],
	)
	uses = _uses_since(add_days(day, -RATE_DAYS))
	types = {
		row.name: row
		for row in frappe.get_all(
			"Instrument Set Type",
			filters={"name": ["in", list({unit.set_type for unit in units}) or [""]]},
			fields=["name", "set_type_name", "current_bom_version"],
		)
	}
	prices, rows = {}, []
	for unit in units:
		remaining = cint(unit.max_cycles) - cint(unit.cycles_used)
		rate = cint(uses.get(unit.name)) / RATE_MONTHS
		if unit.status == END_OF_LIFE or remaining <= 0:
			months = 0
		elif rate:
			months = math.ceil(remaining / rate)
		else:
			continue  # không dùng trong 90 ngày: không dự báo
		if months >= HORIZON_MONTHS:
			continue
		set_type = types.get(unit.set_type) or frappe._dict(
			set_type_name=unit.set_type, current_bom_version=0
		)
		version = cint(unit.cycle_bom_version) or cint(set_type.current_bom_version)
		rows.append(
			{
				"month": getdate(add_months(day, months)).strftime("%Y-%m"),
				"set_unit": unit.name,
				"set_id": unit.set_id,
				"set_type": unit.set_type,
				"set_type_name": set_type.set_type_name,
				"department": unit.department,
				"status": unit.status,
				"cycles_used": cint(unit.cycles_used),
				"max_cycles": cint(unit.max_cycles),
				"remaining": max(remaining, 0),
				"cycles_per_month": round(rate, 2),
				"price": _bom_price(unit.set_type, version, prices),
			}
		)
	return sorted(rows, key=lambda row: (row["month"], row["set_id"] or ""))


# --- bản in và xuất PDF nền (D1, D2) ---------------------------------------------------------------------------------


def _filter_text(kind, filters):
	parts = []
	if kind != "life_forecast":
		start, end = period(filters)
		parts.append(_("Period: {0} to {1}").format(start.strftime(DATE_FORMAT), end.strftime(DATE_FORMAT)))
	if filters.get("equipment"):
		parts.append(_("Machine: {0}").format(filters.equipment))
	if filters.get("department"):
		parts.append(_("Department: {0}").format(filters.department))
	return " · ".join(parts)


def _template():
	with open(frappe.get_app_path("tracecore", *TEMPLATE_PATH), encoding="utf-8") as handle:
		return handle.read()


def _fmt_datetime(value):
	return get_datetime(value).strftime(DATETIME_FORMAT) if value else ""


def render_html(kind, filters, user=None):
	"""HTML đầy đủ của bản in loại `kind` (sổ tiệt khuẩn, báo cáo KSNK, dự báo)."""
	if kind not in KINDS:
		frappe.throw(_("Unknown report: {0}").format(kind))
	filters = frappe._dict(filters or {})
	user = user or frappe.session.user
	context = {
		"kind": kind,
		"title": _(KINDS[kind]["title"]),
		"filter_text": _filter_text(kind, filters),
		"exported_by": get_fullname(user),
		"exported_at": now_datetime().strftime(DATETIME_FORMAT),
		"provisional": kind != "life_forecast" and not is_locked(period(filters)[1]),
		"tc": print_tokens.token_values(),
		"fmt_datetime": _fmt_datetime,
		"fmt_date": lambda value: getdate(value).strftime(DATE_FORMAT) if value else "",
		"fmt_money": lambda value: f"{flt(value):,.0f}".replace(",", "."),
	}
	if kind == "sterilization_log":
		context["rows"] = log_rows(filters)
	elif kind == "ksnk_summary":
		context["summary"] = ksnk_summary(filters)
	else:
		rows = life_forecast(filters)
		months = {}
		for row in rows:
			months.setdefault(row["month"], []).append(row)
		context["months"] = [
			{"month": month, "rows": items, "total": sum(row["price"] for row in items)}
			for month, items in months.items()
		]
		context["grand_total"] = sum(row["price"] for row in rows)
	body = frappe.render_template(_template(), {"r": context})
	title = escape_html(context["title"])
	lang = escape_html(frappe.local.lang or "vi")
	return (
		f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n<title>{title}</title>\n</head>\n'
		f'<body>\n<div class="print-format">\n{body}\n</div>\n</body>\n</html>\n'
	)


def render_pdf(kind, filters, user=None):
	from frappe.utils.pdf import get_pdf

	options = {"page-size": "A4", "orientation": "Landscape" if KINDS[kind]["landscape"] else "Portrait"}
	return get_pdf(render_html(kind, filters, user), options)


def build_export(kind, filters, user):
	"""Job RQ ``long``: sinh PDF, lưu File riêng tư, báo người xuất (chuông Desk + realtime). Trả tên File."""
	filters = frappe._dict(frappe.parse_json(filters) if isinstance(filters, str) else (filters or {}))
	pdf = render_pdf(kind, filters, user)
	suffix = (
		f"{filters.from_date}_{filters.to_date}"
		if kind != "life_forecast"
		else getdate().strftime("%Y-%m-%d")
	)
	file = frappe.get_doc(
		{"doctype": "File", "file_name": f"{kind}_{suffix}.pdf", "content": pdf, "is_private": 1}
	).insert(ignore_permissions=True)
	title = _(KINDS[kind]["title"])
	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": user,
			"type": "Alert",
			"subject": _("{0} is ready to download").format(title),
			"link": file.file_url,
		}
	).insert(ignore_permissions=True)
	frappe.publish_realtime(
		"tc_report_ready", {"title": title, "file_url": file.file_url}, user=user, after_commit=True
	)
	return file.name
