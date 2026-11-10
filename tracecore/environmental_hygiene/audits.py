"""Phiếu vệ sinh môi trường và hạ tầng gắn vùng (FEAT-070; FR-M15-02, .1, FR-M15-06, .1; UC-54 bước 3, 7, E4;
ADR-015; A-148 e).

M15 không import M12: đọc `Audit Session`/`Audit Template` qua ``frappe.db``/``frappe.get_all`` và kiểm phiếu bằng
``doc_events["Audit Session"]["validate"]`` (``validate_session``).

- Phiếu loại Vệ sinh môi trường / Cơ sở hạ tầng của khoa đã khai báo vùng phải gắn vùng cùng khoa; loại khác bỏ vùng.
- Hạ tầng: ``next_due`` trống thì = ngày phiếu + ``inspection_interval_days`` của mẫu; không có chu kỳ thì bắt buộc nhập.
  Một "hệ thống" = cặp (mã mẫu hạ tầng, vùng); phiếu đã ghi sổ mới nhất quyết định hạn (A-148 Q2).
- Tỷ lệ đạt VSMT theo mức nguy cơ, khoa, bên chịu trách nhiệm (tách từng NCC); tỷ lệ hệ thống kiểm tra đúng hạn theo
  ``infra_category`` (quá hạn không tính đúng hạn); nhắc trước hạn 7 ngày.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, today

from tracecore.core import notification
from tracecore.environmental_hygiene import zones
from tracecore.environmental_hygiene.zones import blocked

SESSION = "Audit Session"
TEMPLATE = "Audit Template"
CLEANING, INFRA = "Environmental Hygiene", "Infrastructure"
ZONE_TYPES = (CLEANING, INFRA)
PASS = "Pass"  # nosec B105 - kết quả phiếu, không phải mật khẩu
DUE_SOON_DAYS = 7
OVERDUE, DUE_SOON, IN_DATE = "Overdue", "Due Soon", "In Date"
INFRA_DUE_EVENT = "ENV_INFRA_DUE"


def _template(name):
	return (
		frappe.db.get_value(
			TEMPLATE,
			name,
			["audit_type", "inspection_interval_days", "infra_category", "template_code", "title"],
			as_dict=True,
		)
		or frappe._dict()
	)


def validate_session(doc, method=None):
	"""``doc_events["Audit Session"]["validate"]``: vùng và hạn kế tiếp của phiếu VSMT/hạ tầng."""
	template = _template(doc.audit_template)
	if template.audit_type not in ZONE_TYPES:
		doc.environment_zone = None
		doc.next_due = None
		return
	if doc.environment_zone:
		zone = frappe.db.get_value(
			zones.DOCTYPE, doc.environment_zone, ["department", "disabled", "area_name"], as_dict=True
		)
		if not zone or cint(zone.disabled) or zone.department != doc.department:
			raise blocked(
				"ENV_ZONE_MISMATCH",
				_("Zone not in this department"),
				_("Zone {0} is not an active zone of department {1}.").format(
					doc.environment_zone, doc.department
				),
				_("Choose a zone of the audited department."),
			)
	elif frappe.db.exists(zones.DOCTYPE, {"department": doc.department, "disabled": 0}):
		raise blocked(
			"ENV_ZONE_REQUIRED",
			_("Zone required"),
			_("Department {0} has cleaning zones; this audit is not linked to a zone.").format(
				doc.department
			),
			_("Choose the zone you audited, then post the audit."),
		)
	if template.audit_type != INFRA:
		doc.next_due = None
		return
	if not doc.next_due and cint(template.inspection_interval_days):
		doc.next_due = add_days(getdate(doc.audit_date or today()), cint(template.inspection_interval_days))
	if not doc.next_due:
		raise blocked(
			"ENV_NEXT_DUE_REQUIRED",
			_("Next inspection date required"),
			_("Template {0} has no inspection interval.").format(doc.audit_template),
			_("Enter the next inspection date, then post the audit."),
		)


# --- tỷ lệ đạt VSMT (FR-M15-02, .1) ---------------------------------------------------------------------------------


def _cleaning_sessions(from_date, to_date, department=None):
	filters = {
		"docstatus": 1,
		"audit_type": CLEANING,
		"environment_zone": ["is", "set"],
		"audit_date": ["between", [getdate(from_date), getdate(to_date)]],
	}
	if department:
		filters["department"] = department
	rows = frappe.get_all(SESSION, filters=filters, fields=["name", "environment_zone", "result"])
	zone_info = {}
	if rows:
		for zone in frappe.get_all(
			zones.DOCTYPE,
			filters={"name": ["in", list({row.environment_zone for row in rows})]},
			fields=[
				"name",
				"department",
				"department_name",
				"risk_level",
				"responsible_party",
				"supplier",
				"supplier_name",
			],
		):
			zone_info[zone.name] = zone
	return [(row, zone_info[row.environment_zone]) for row in rows if row.environment_zone in zone_info]


def _group(pairs, key_of, label_of):
	groups = {}
	for row, zone in pairs:
		key = key_of(zone)
		entry = groups.setdefault(key, {"key": key, "label": label_of(zone), "total": 0, "passed": 0})
		entry["total"] += 1
		entry["passed"] += 1 if row.result == PASS else 0
	result = sorted(groups.values(), key=lambda entry: cstr_label(entry["label"]))
	for entry in result:
		entry["pct"] = round(flt(entry["passed"]) * 100 / entry["total"], 1) if entry["total"] else None
	return result


def cstr_label(value):
	return (value or "").lower()


def _party(zone):
	return (
		zone.supplier
		if zone.responsible_party == zones.PARTY_VENDOR and zone.supplier
		else zones.PARTY_DEPARTMENT
	)


def pass_rates(from_date, to_date, department=None):
	pairs = _cleaning_sessions(from_date, to_date, department)
	return {
		"total": len(pairs),
		"passed": sum(1 for row, _zone in pairs if row.result == PASS),
		"by_risk": _group(pairs, lambda zone: zone.risk_level, lambda zone: zone.risk_level),
		"by_department": _group(
			pairs, lambda zone: zone.department, lambda zone: zone.department_name or zone.department
		),
		"by_party": _group(
			pairs,
			_party,
			lambda zone: zone.supplier_name or zone.supplier
			if _party(zone) != zones.PARTY_DEPARTMENT
			else _("Department"),
		),
	}


def high_risk_levels():
	return frappe.get_all(zones.RISK_DOCTYPE, filters={"is_high_risk": 1}, pluck="name")


def high_risk_pass(from_date, to_date, department=None):
	"""(Đạt, tổng) phiếu VSMT của vùng có mức tính là nguy cơ cao (QĐ 38 ≥ 80 %)."""
	levels = set(high_risk_levels())
	pairs = [
		pair for pair in _cleaning_sessions(from_date, to_date, department) if pair[1].risk_level in levels
	]
	return sum(1 for row, _zone in pairs if row.result == PASS), len(pairs)


# --- hạ tầng (FR-M15-06, .1) ----------------------------------------------------------------------------------------


def infra_systems(on=None, department=None):
	"""Hệ thống hạ tầng (mã mẫu, vùng) với lần kiểm tra mới nhất, hạn kế tiếp và trạng thái tại ``on``."""
	on = getdate(on or today())
	filters = {
		"docstatus": 1,
		"audit_type": INFRA,
		"environment_zone": ["is", "set"],
		"audit_date": ["<=", on],
	}
	if department:
		filters["department"] = department
	rows = frappe.get_all(
		SESSION,
		filters=filters,
		fields=[
			"name",
			"template_code",
			"template_title",
			"audit_template",
			"environment_zone",
			"department",
			"department_name",
			"audit_date",
			"next_due",
			"result",
		],
		order_by="audit_date desc, creation desc",
	)
	latest = {}
	for row in rows:
		latest.setdefault((row.template_code, row.environment_zone), row)
	areas = {}
	if latest:
		areas = dict(
			frappe.get_all(
				zones.DOCTYPE,
				filters={"name": ["in", list({key[1] for key in latest})]},
				fields=["name", "area_name"],
				as_list=True,
			)
		)
	categories = {}
	result = []
	for (code, zone), row in latest.items():
		if row.audit_template not in categories:
			categories[row.audit_template] = _template(row.audit_template).infra_category
		days = date_diff(row.next_due, on) if row.next_due else None
		status = OVERDUE if days is None or days < 0 else DUE_SOON if days <= DUE_SOON_DAYS else IN_DATE
		result.append(
			{
				"template_code": code,
				"title": row.template_title,
				"infra_category": categories[row.audit_template],
				"zone": zone,
				"area_name": areas.get(zone),
				"department": row.department,
				"department_name": row.department_name,
				"session": row.name,
				"last_on": row.audit_date,
				"next_due": row.next_due,
				"days_left": days,
				"result": row.result,
				"status": status,
			}
		)
	result.sort(key=lambda item: (item["next_due"] is None, str(item["next_due"] or "")))
	return result


def on_time(category, on=None, department=None):
	"""(đúng hạn, tổng) hệ thống của một loại hạ tầng; quá hạn không tính đúng hạn (FR-M15-06.1)."""
	systems = [row for row in infra_systems(on, department) if row["infra_category"] == category]
	return sum(1 for row in systems if row["status"] != OVERDUE), len(systems)


def run_daily(on=None):
	"""Scheduler hằng ngày: nhắc R01/R11 trước hạn kiểm tra hạ tầng 7 ngày (FR-M15-06)."""
	on = getdate(on or today())
	for row in infra_systems(on):
		if row["days_left"] == DUE_SOON_DAYS:
			notification.emit(
				INFRA_DUE_EVENT,
				frappe._dict(doctype=SESSION, name=row["session"]),
				subject=_("Infrastructure inspection due on {0} — {1}, {2}").format(
					frappe.format(row["next_due"], "Date"), row["title"], row["area_name"]
				),
			)
