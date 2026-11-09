"""Cơ cấu KSNK bắt buộc theo quy mô giường (FEAT-057; FR-M11-01..03; BRU-ICP-001..003; A-132).

``compute()`` đọc IC Program Settings, Hội đồng hiệu lực, mạng lưới viên và trả bảng thành phần Đủ/Thiếu bằng chữ cho
SCR-47, Script Report "Cơ cấu KSNK còn thiếu" và badge menu. ``check`` là validate hook dùng chung của IC Program
Settings, IC Committee và IC Network Member (đăng ký trong hooks). Mỗi thành phần có ``status`` mã cố định
(``ok`` / ``missing`` / ``warning`` / ``optional`` / ``na``) và ``status_label`` đã dịch — thiếu luôn có chữ "Thiếu".
"""

import math

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from tracecore.core import audit

SETTINGS = "IC Program Settings"
COMMITTEE = "IC Committee"
NETWORK = "IC Network Member"
SCREEN_SLUG = "co-cau"

# TT 16/2018 Điều 16, 22: từ 150 giường cần Hội đồng + khoa KSNK (ngưỡng pháp lý, không phải tỷ lệ cấu hình)
COMMITTEE_MIN_BEDS = 150
DEFAULT_RATIO = 150
# BRU-ICP-002: thiếu các khối này vẫn ghi sổ được nhưng cảnh báo (FR-M11-02.2)
REQUIRED_REPRESENTING = ("Microbiology and Laboratory", "Pharmacy", "High-risk Clinical")
SINGLE_ROLES = ("Chair", "Secretary")
DOCTOR_TYPES = frozenset({"Doctor"})
NURSE_TYPES = frozenset({"Nurse", "Midwife", "Technician"})
MEMBER_GROUPS = (("doctor", DOCTOR_TYPES), ("nurse", NURSE_TYPES))


def required_surveillance(bed_count, ratio):
	"""Số giám sát viên tối thiểu = giường ÷ tỷ lệ, làm tròn lên, tối thiểu 1 (BRU-ICP-001; giả định OQ-V12-04)."""
	ratio = cint(ratio) or DEFAULT_RATIO
	return max(1, math.ceil(cint(bed_count) / ratio))


def member_group(member_type):
	return "doctor" if member_type in DOCTOR_TYPES else "nurse"


def group_types(group):
	return dict(MEMBER_GROUPS)[group]


def _scale(settings):
	if not cint(settings.has_inpatient):
		return "outpatient"
	return "large" if cint(settings.bed_count) >= COMMITTEE_MIN_BEDS else "small"


# --- Hội đồng ----------------------------------------------------------------------------------------------------


def active_committee(on=None):
	"""Hội đồng đã ghi sổ có hiệu lực tại ngày `on`, mới nhất theo `valid_from` (UC-40 A3); None nếu không có."""
	on = on or today()
	rows = frappe.get_all(
		COMMITTEE,
		filters={"docstatus": 1, "valid_from": ["<=", on]},
		or_filters=[["valid_to", "is", "not set"], ["valid_to", ">=", on]],
		pluck="name",
		order_by="valid_from desc, creation desc",
		limit=1,
	)
	return frappe.get_doc(COMMITTEE, rows[0]) if rows else None


def missing_representatives(committee):
	present = {row.representing for row in committee.members}
	return [group for group in REQUIRED_REPRESENTING if group not in present]


def warn_missing_representatives(committee):
	"""FR-M11-02.2: ghi sổ vẫn thành công, cảnh báo khối thiếu và ghi Audit Log."""
	missing = missing_representatives(committee)
	if not missing:
		return
	frappe.msgprint(
		_("Missing committee representative: {0}. The committee is still recorded.").format(
			", ".join(_(group) for group in missing)
		),
		title=_("Committee warning"),
		indicator="orange",
	)
	audit.log(
		"Update",
		COMMITTEE,
		committee.name,
		new={"missing_representatives": missing},
		reason="IC_COMMITTEE_REPRESENTATIVE_MISSING: " + ", ".join(missing),
	)


def _committee_summary(committee):
	if not committee:
		return None
	return {
		"name": committee.name,
		"decision_no": committee.decision_no,
		"valid_from": str(committee.valid_from) if committee.valid_from else None,
		"valid_to": str(committee.valid_to) if committee.valid_to else None,
		"members": [
			{
				"employee": row.employee,
				"employee_name": row.employee_name,
				"committee_role": row.committee_role,
				"representing": row.representing,
			}
			for row in committee.members
		],
		"missing_representatives": missing_representatives(committee),
	}


# --- mạng lưới ---------------------------------------------------------------------------------------------------


def required_departments():
	return frappe.get_all(
		"Department",
		filters={"tc_ic_network_required": 1, "disabled": 0, "is_group": 0},
		fields=["name", "department_name"],
		order_by="department_name asc",
	)


def _department_label(missing):
	if missing == ["doctor"]:
		return _("Missing doctor")
	if missing == ["nurse"]:
		return _("Missing nurse/midwife/technician")
	return _("Missing doctor and nurse/midwife/technician")


def department_rows():
	"""Mỗi khoa bắt buộc: số bác sĩ, số ĐD/HS/KTV đang hiệu lực và nhóm còn thiếu (BRU-ICP-003)."""
	departments = required_departments()
	if not departments:
		return []
	counts = {}
	for row in frappe.get_all(
		NETWORK,
		filters={"is_active": 1, "department": ["in", [d.name for d in departments]]},
		fields=["department", "member_type"],
	):
		key = (row.department, member_group(row.member_type))
		counts[key] = counts.get(key, 0) + 1
	rows = []
	for department in departments:
		doctors = counts.get((department.name, "doctor"), 0)
		nurses = counts.get((department.name, "nurse"), 0)
		missing = [group for group, value in (("doctor", doctors), ("nurse", nurses)) if not value]
		rows.append(
			{
				"department": department.name,
				"department_name": department.department_name or department.name,
				"doctors": doctors,
				"nurses": nurses,
				"missing": missing,
				"status": "missing" if missing else "ok",
				"status_label": _department_label(missing) if missing else _("Sufficient"),
			}
		)
	return rows


# --- bảng thành phần ---------------------------------------------------------------------------------------------


def _component(key, label, requirement, current, status, status_label, missing_count=0, **extra):
	return {
		"key": key,
		"label": label,
		"requirement": requirement,
		"current": current,
		"status": status,
		"status_label": status_label,
		"missing_count": missing_count,
		"required": extra.get("required"),
		"actual": extra.get("actual"),
	}


def _na(key, label):
	return _component(key, label, _("Not applicable (no inpatient care)"), "—", "na", _("Not applicable"))


def _committee_component(scale, committee):
	label = _("IC Committee")
	if scale == "outpatient":
		return _na("committee", label)
	current = _("{0}, {1} members").format(committee.name, len(committee.members)) if committee else "—"
	if scale == "small":
		return _component(
			"committee",
			label,
			_("Not required (under {0} beds)").format(COMMITTEE_MIN_BEDS),
			current,
			"optional",
			_("Not required"),
		)
	requirement = _("Required (≥ {0} beds)").format(COMMITTEE_MIN_BEDS)
	if not committee:
		return _component("committee", label, requirement, current, "missing", _("Missing", context="IC Structure"), 1)
	missing = missing_representatives(committee)
	if missing:
		return _component(
			"committee",
			label,
			requirement,
			current,
			"warning",
			_("Present — missing representative: {0}").format(", ".join(_(group) for group in missing)),
		)
	return _component("committee", label, requirement, current, "ok", _("Sufficient"))


def _department_component(scale, settings):
	label = _("Infection Control Department") if scale == "large" else _("Infection Control Unit")
	if scale == "outpatient":
		return _na("ic_department", label)
	if settings.ic_department:
		name = frappe.db.get_value("Department", settings.ic_department, "department_name")
		return _component("ic_department", label, _("Required"), name or settings.ic_department, "ok", _("Sufficient"))
	return _component("ic_department", label, _("Required"), "—", "missing", _("Missing", context="IC Structure"), 1)


def _network_component(scale, departments):
	label = _("IC Network")
	if scale == "outpatient":
		return _na("network", label)
	requirement = _("Each department ≥ 1 doctor + ≥ 1 nurse/midwife/technician")
	if not departments:
		return _component(
			"network",
			label,
			requirement,
			_("No department is marked as requiring a network"),
			"missing",
			_("Missing: no department marked"),
			1,
		)
	missing = sum(1 for row in departments if row["status"] == "missing")
	current = _("{0}/{1} departments sufficient").format(len(departments) - missing, len(departments))
	if missing:
		return _component(
			"network", label, requirement, current, "missing", _("Missing {0} departments").format(missing), missing
		)
	return _component("network", label, requirement, current, "ok", _("Sufficient"))


def _surveillance_component(scale, settings):
	active = [row for row in settings.surveillance_staff if cint(row.is_active)]
	if scale == "outpatient":
		label, required, actual = _("IC Person in Charge"), 1, len(active)
		requirement = _("≥ 1 person")
	elif scale == "small":
		label, required = _("Full-time IC Officer"), 1
		actual = sum(1 for row in active if cint(row.full_time))
		requirement = _("≥ 1 person")
	else:
		label = _("Full-time Surveillance Officers")
		ratio = cint(settings.surveillance_ratio_beds) or DEFAULT_RATIO
		required = required_surveillance(settings.bed_count, ratio)
		actual = sum(1 for row in active if cint(row.full_time))
		requirement = _("≥ {0} people ({1} ÷ {2}, rounded up)").format(required, cint(settings.bed_count), ratio)
	current = _("{0} people").format(actual)
	if actual < required:
		return _component(
			"surveillance",
			label,
			requirement,
			current,
			"missing",
			_("Missing {0}").format(required - actual),
			required - actual,
			required=required,
			actual=actual,
		)
	return _component(
		"surveillance", label, requirement, current, "ok", _("Sufficient"), required=required, actual=actual
	)


def compute():
	"""Bảng cơ cấu KSNK hiện tại (FR-M11-01): thành phần, khoa của mạng lưới, Hội đồng hiệu lực."""
	settings = frappe.get_single(SETTINGS)
	scale = _scale(settings)
	committee = active_committee()
	departments = department_rows() if scale != "outpatient" else []
	components = [
		_committee_component(scale, committee),
		_department_component(scale, settings),
		_network_component(scale, departments),
		_surveillance_component(scale, settings),
	]
	return {
		"scale": scale,
		"bed_count": cint(settings.bed_count),
		"components": components,
		"departments": departments,
		"committee": _committee_summary(committee),
		"missing_total": sum(1 for row in components if row["status"] == "missing"),
	}


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: số thành phần cơ cấu còn thiếu trên mục menu SCR-47."""
	return {SCREEN_SLUG: compute()["missing_total"]}


# --- validate hook -----------------------------------------------------------------------------------------------


def _duplicates(values):
	seen, duplicated = set(), []
	for value in values:
		if value in seen and value not in duplicated:
			duplicated.append(value)
		seen.add(value)
	return duplicated


def _check_settings(doc):
	duplicated = _duplicates(row.employee for row in doc.surveillance_staff if row.employee)
	if duplicated:
		frappe.throw(_("Employee {0} is listed more than once in surveillance staff.").format(", ".join(duplicated)))


def _check_committee(doc):
	if doc.valid_to and doc.valid_from and getdate(doc.valid_to) < getdate(doc.valid_from):
		frappe.throw(_("Valid To cannot be before Valid From."))
	duplicated = _duplicates(row.employee for row in doc.members if row.employee)
	if duplicated:
		frappe.throw(_("Employee {0} is listed more than once in the committee.").format(", ".join(duplicated)))
	if cint(doc.docstatus) != 1:
		return
	problems = []
	for role in SINGLE_ROLES:
		count = sum(1 for row in doc.members if row.committee_role == role)
		if count == 0:
			problems.append(_("Missing {0}").format(_(role)))
		elif count > 1:
			problems.append(_("{0} {1} (only 1 allowed)").format(count, _(role)))
	if problems:
		frappe.throw(
			_("The committee must have exactly one Chair and one Secretary: {0}.").format("; ".join(problems)),
			title=_("Committee not complete"),
		)


def _check_network_member(doc):
	if not cint(doc.is_active):
		return
	if frappe.db.exists(
		NETWORK,
		{"employee": doc.employee, "department": doc.department, "is_active": 1, "name": ["!=", doc.name or ""]},
	):
		frappe.throw(_("{0} is already an active network member of {1}.").format(doc.employee, doc.department))


CHECKS = {SETTINGS: _check_settings, COMMITTEE: _check_committee, NETWORK: _check_network_member}


def check(doc, method=None):
	"""Validate hook ``infection_program.structure.check`` (FEAT-057)."""
	handler = CHECKS.get(doc.doctype)
	if handler:
		handler(doc)
