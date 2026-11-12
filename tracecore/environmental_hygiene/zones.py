"""Vùng vệ sinh (FEAT-070; FR-M15-01, .1, .2, FR-M15-04.1; BRU-ENV-001, BRU-ENV-003; UC-54 E1; A-148 a).

- Vùng bắt buộc mức nguy cơ (``Environment Risk Level`` đang dùng) và bên chịu trách nhiệm; thuê ngoài thì bắt buộc NCC.
- Số phiếu tối thiểu/tháng trống thì lấy theo mức (BRU-ENV-001); ``coverage`` đếm phiếu VSMT đã ghi sổ gắn vùng trong
  tháng và đánh dấu vùng thiếu (FR-M15-01.1). Phiếu đọc qua ``frappe.get_all`` (M12 là engine, không import).
- Cờ "Chờ lấy mẫu lại" (``refresh_flag``) do dịch vụ mẫu đặt/tắt: vùng còn mẫu Không đạt chưa có mẫu lại Đạt.
- R08/R12 chỉ thấy vùng và mẫu của khoa có User Permission Department (FR-M15-01.2, NFR-SEC-09).
"""

import frappe
from frappe import _
from frappe.utils import cint, get_first_day, get_last_day, getdate

from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Environment Zone"
RISK_DOCTYPE = "Environment Risk Level"
SAMPLE_DOCTYPE = "Environmental Sample"
SESSION_DOCTYPE = "Audit Session"
CLEANING_AUDIT = "Environmental Hygiene"
PARTY_DEPARTMENT, PARTY_VENDOR = "Department", "Outsourced Vendor"
PASS, FAIL = "Pass", "Fail"
WIDE_ROLES = frozenset({"TC R01", "TC R02", "TC R10", "TC R11", "TC R13", "System Manager"})
DEPT_ROLES = frozenset({"TC R08", "TC R12"})


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


def validate(doc):
	"""Gọi từ ``EnvironmentZone.validate``."""
	level = (
		frappe.db.get_value(RISK_DOCTYPE, doc.risk_level, ["min_audits_per_month", "disabled"], as_dict=True)
		if doc.risk_level
		else None
	)
	if not level or cint(level.disabled):
		raise blocked(
			"ENV_ZONE_RISK_REQUIRED",
			_("Risk level required"),
			_("Zone {0} has no risk level in use.").format(doc.area_name or ""),
			_("Choose a risk level configured by the head of infection control, then save."),
		)
	if doc.responsible_party not in (PARTY_DEPARTMENT, PARTY_VENDOR):
		raise blocked(
			"ENV_ZONE_PARTY_REQUIRED",
			_("Responsible party required"),
			_("Zone {0} has no party responsible for cleaning.").format(doc.area_name or ""),
			_("Choose Department or Outsourced Vendor, then save."),
		)
	if doc.responsible_party == PARTY_VENDOR and not doc.supplier:
		raise blocked(
			"ENV_ZONE_VENDOR_REQUIRED",
			_("Outsourced vendor required"),
			_("Zone {0} is cleaned by an outsourced vendor but no vendor is chosen.").format(
				doc.area_name or ""
			),
			_("Choose the cleaning vendor, then save."),
		)
	if doc.responsible_party == PARTY_DEPARTMENT:
		doc.supplier = None
		doc.supplier_name = None
	if not cint(doc.min_audits_per_month):
		doc.min_audits_per_month = cint(level.min_audits_per_month)


# --- số phiếu tối thiểu trong tháng (FR-M15-01, .1) ------------------------------------------------------------------


def active_zones(department=None):
	filters = {"disabled": 0}
	if department:
		filters["department"] = department
	return frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"area_name",
			"department",
			"department_name",
			"risk_level",
			"responsible_party",
			"supplier",
			"supplier_name",
			"min_audits_per_month",
			"awaiting_resample",
			"flag_sample",
		],
		order_by="department_name asc, area_name asc",
	)


def coverage(on, department=None):
	"""Mỗi vùng đang dùng: số phiếu VSMT đã ghi sổ trong tháng của ``on`` so với số tối thiểu."""
	on = getdate(on)
	zones = active_zones(department)
	done = {}
	if zones:
		rows = frappe.get_all(
			SESSION_DOCTYPE,
			filters={
				"docstatus": 1,
				"audit_type": CLEANING_AUDIT,
				"environment_zone": ["in", [zone.name for zone in zones]],
				"audit_date": ["between", [get_first_day(on), get_last_day(on)]],
			},
			fields=["environment_zone", "count(name) as n"],
			group_by="environment_zone",
		)
		done = {row.environment_zone: cint(row.n) for row in rows}
	result = []
	for zone in zones:
		required = cint(zone.min_audits_per_month)
		count = done.get(zone.name, 0)
		result.append(
			{
				"zone": zone.name,
				"area_name": zone.area_name,
				"department": zone.department,
				"department_name": zone.department_name,
				"risk_level": zone.risk_level,
				"responsible_party": zone.responsible_party,
				"supplier": zone.supplier,
				"supplier_name": zone.supplier_name,
				"required": required,
				"done": count,
				"short": count < required,
				"awaiting_resample": cint(zone.awaiting_resample),
				"flag_sample": zone.flag_sample,
			}
		)
	return result


def short_zones(on, department=None):
	return [row for row in coverage(on, department) if row["short"]]


# --- cờ "Chờ lấy mẫu lại" (FR-M15-04.1, BRU-ENV-003) -----------------------------------------------------------------


def _passing_resample(name, resamples):
	"""Mẫu lại Đạt giải quyết mẫu Không đạt ``name`` (trực tiếp, hoặc qua chuỗi mẫu lại Không đạt); None nếu chưa có."""
	for child in resamples.get(name, ()):
		if child.result == PASS:
			return child.name
		found = _passing_resample(child.name, resamples)
		if found:
			return found
	return None


def _zone_samples(zone):
	rows = frappe.get_all(
		SAMPLE_DOCTYPE,
		filters={"environment_zone": zone, "docstatus": 1},
		fields=["name", "result", "is_resample_of", "sampled_on", "creation"],
		order_by="sampled_on asc, creation asc",
	)
	resamples = {}
	for row in rows:
		if row.is_resample_of:
			resamples.setdefault(row.is_resample_of, []).append(row)
	return rows, resamples


def unresolved_failures(zone):
	rows, resamples = _zone_samples(zone)
	return [row.name for row in rows if row.result == FAIL and not _passing_resample(row.name, resamples)]


def resolving_resamples(zone):
	"""``{mẫu Không đạt: mẫu lại Đạt đã giải quyết nó}`` của vùng — chỉ các mẫu đã được giải quyết."""
	rows, resamples = _zone_samples(zone)
	result = {}
	for row in rows:
		if row.result == FAIL:
			found = _passing_resample(row.name, resamples)
			if found:
				result[row.name] = found
	return result


def refresh_flag(zone):
	"""Bật cờ khi còn mẫu Không đạt chưa giải quyết (giữ mẫu mới nhất), tắt khi không còn."""
	if not zone:
		return
	pending = unresolved_failures(zone)
	frappe.db.set_value(
		DOCTYPE,
		zone,
		{"awaiting_resample": 1 if pending else 0, "flag_sample": pending[-1] if pending else None},
		update_modified=False,
	)


# --- phạm vi khoa (FR-M15-01.2) ---------------------------------------------------------------------------------------


def allowed_departments(user=None):
	"""None = mọi khoa; danh sách = chỉ khoa có User Permission (R08/R12)."""
	user = user or frappe.session.user
	if user == "Administrator":
		return None
	roles = set(frappe.get_roles(user))
	if roles & WIDE_ROLES or not roles & DEPT_ROLES:
		return None
	return frappe.get_all("User Permission", filters={"user": user, "allow": "Department"}, pluck="for_value")


def _conditions(doctype, user=None):
	departments = allowed_departments(user)
	if departments is None:
		return ""
	if not departments:
		return "1=0"
	values = ", ".join(frappe.db.escape(name) for name in departments)
	return f"`tab{doctype}`.`department` in ({values})"


def query_conditions(user=None):
	return _conditions(DOCTYPE, user)


def sample_query_conditions(user=None):
	return _conditions(SAMPLE_DOCTYPE, user)


def has_permission(doc, user=None, permission_type=None):
	departments = allowed_departments(user)
	if departments is None:
		return None
	return doc.department in departments
