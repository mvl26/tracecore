"""Cơ cấu KSNK bắt buộc theo quy mô giường (FEAT-057, FEAT-094; FR-M11-01..03; BRU-ICP-001..003, 006, 007; A-132, A-138).

``compute()`` đọc IC Program Settings, bộ tiêu chí cơ cấu đang hiệu lực (``structure_profile.active_profile``), Hội đồng
hiệu lực, mạng lưới viên và trả bảng thành phần bằng chữ cho SCR-47, Script Report "Cơ cấu KSNK còn thiếu" và badge
menu. ``check`` là validate hook dùng chung của IC Program Settings, IC Committee và IC Network Member (đăng ký trong
hooks). Mỗi thành phần có ``status`` mã cố định (``ok`` / ``missing`` / ``warning`` / ``unverified`` / ``optional`` /
``na``) và ``status_label`` đã dịch — thiếu luôn có chữ "Thiếu", chưa xác minh có chữ "Chưa xác minh".

Mọi tiêu chí chuyên môn (ngưỡng giường, khối bắt buộc của Hội đồng, quy tắc mạng lưới, yêu cầu theo vai trò) đọc từ
bộ tiêu chí (FR-M11-01.8). Chưa có bản Đã duyệt → chỉ kiểm phần đếm như FEAT-057, ngưỡng lấy giá trị mặc định của
trường DocType, kèm ``profile_notice`` (OQ-V12-16).
"""

import math

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from tracecore.core import audit
from tracecore.infection_program import qualification, structure_profile

SETTINGS = "IC Program Settings"
COMMITTEE = "IC Committee"
NETWORK = "IC Network Member"
SCREEN_SLUG = "co-cau"

DEFAULT_RATIO = 150
SINGLE_ROLES = ("Chair", "Secretary")
DOCTOR_TYPES = frozenset({"Doctor"})
NURSE_TYPES = frozenset({"Nurse", "Midwife", "Technician"})
MEMBER_GROUPS = (("doctor", DOCTOR_TYPES), ("nurse", NURSE_TYPES))
NETWORK_ANY = "Any One Member"
BLOCK = "Block"
ROUND_DOWN = "Down"
# vai trò nhân sự khoa/bộ phận KSNK theo thứ tự xét (A-138 d) → khóa thành phần
ROLE_KEYS = (
	("Head", "head"),
	("Head Nurse", "head_nurse"),
	("Person in Charge", "person_in_charge"),
	("Surveillance Officer", "surveillance"),
)
SECRETARY_ROLES = frozenset({"Head", "Person in Charge"})


def required_surveillance(bed_count, ratio, rounding="Up"):
	"""Số giám sát viên tối thiểu = giường ÷ tỷ lệ, làm tròn lên (mặc định) hoặc xuống, tối thiểu 1 (BRU-ICP-001)."""
	ratio = cint(ratio) or DEFAULT_RATIO
	value = cint(bed_count) / ratio
	return max(1, math.floor(value) if rounding == ROUND_DOWN else math.ceil(value))


def member_group(member_type):
	return "doctor" if member_type in DOCTOR_TYPES else "nurse"


def group_types(group):
	return dict(MEMBER_GROUPS)[group]


# --- bộ tiêu chí ---------------------------------------------------------------------------------------------------


def rules(profile=None):
	"""Tham số cơ cấu của bản đang hiệu lực; chưa có bản Đã duyệt → giá trị mặc định của DocType, không kiểm điều kiện."""
	source = profile.get if profile else structure_profile.field_default
	return {
		"profile": profile,
		"department_min_beds": cint(source("department_min_beds")),
		"committee_min_beds": cint(source("committee_min_beds")),
		"network_rule": source("network_rule"),
		"severity": source("committee_rule_severity"),
		"allow_both": cint(source("allow_one_person_both_roles")) if profile else 0,
	}


def _scale(settings, criteria):
	if not cint(settings.has_inpatient):
		return "outpatient"
	return "large" if cint(settings.bed_count) >= criteria["department_min_beds"] else "small"


def _committee_required(scale, settings, criteria):
	return scale != "outpatient" and cint(settings.bed_count) >= criteria["committee_min_beds"]


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


def _active_staff(settings, roles=None):
	return [
		row
		for row in settings.get("surveillance_staff") or []
		if cint(row.is_active) and row.employee and (roles is None or row.ic_role in roles)
	]


def committee_problems(committee, profile=None, settings=None):
	"""Khối / vai trò thiếu, Chủ tịch, Thư ký so với bộ tiêu chí (FR-M11-02.2..02.4; BRU-ICP-002).

	Mỗi mục ``{code, text, blocking, group}``; ``blocking`` = 0 cho lời nhắc khai người đứng đầu. Không có bộ tiêu chí
	đã duyệt → danh sách rỗng (chỉ kiểm đúng 1 Chủ tịch + 1 Thư ký).
	"""
	profile = profile if profile is not None else structure_profile.active_profile()
	if not profile:
		return []
	settings = settings or frappe.get_single(SETTINGS)
	problems = []
	for row in profile.committee_requirements:
		if row.requirement_type == structure_profile.REPRESENTING:
			count = sum(1 for member in committee.members if member.representing == row.representing)
			if count < cint(row.min_count):
				problems.append(
					{
						"code": "REPRESENTATIVE",
						"group": row.representing,
						"text": _("Missing representative: {0}").format(_(row.representing)),
						"blocking": 1,
					}
				)
		else:
			count = sum(1 for member in committee.members if member.committee_role == row.committee_role)
			if count < cint(row.min_count):
				problems.append(
					{
						"code": "ROLE",
						"group": row.committee_role,
						"text": _("Missing committee role: {0} (at least {1})").format(
							_(row.committee_role), cint(row.min_count)
						),
						"blocking": 1,
					}
				)
	chairs = [member.employee for member in committee.members if member.committee_role == "Chair"]
	if not settings.director:
		problems.append(
			{
				"code": "DIRECTOR_NOT_SET",
				"group": None,
				"text": _(
					"Head of facility is not declared in IC Program Settings; the Chair was not checked."
				),
				"blocking": 0,
			}
		)
	elif chairs and settings.director not in chairs:
		problems.append(
			{
				"code": "CHAIR_NOT_DIRECTOR",
				"group": None,
				"text": _("The Chair is not the head of facility ({0}).").format(
					frappe.db.get_value("Employee", settings.director, "employee_name") or settings.director
				),
				"blocking": 1,
			}
		)
	secretaries = [member.employee for member in committee.members if member.committee_role == "Secretary"]
	allowed = {row.employee for row in _active_staff(settings, SECRETARY_ROLES)}
	if secretaries and not set(secretaries) & allowed:
		problems.append(
			{
				"code": "SECRETARY_NOT_IC_LEAD",
				"group": None,
				"text": _(
					"The Secretary is not the active head or person in charge of infection control in IC Program Settings."
				),
				"blocking": 1,
			}
		)
	return problems


def missing_representatives(committee):
	"""Khối đại diện còn thiếu theo bộ tiêu chí đang hiệu lực (rỗng khi chưa có bản Đã duyệt)."""
	return [row["group"] for row in committee_problems(committee) if row["code"] == "REPRESENTATIVE"]


def warn_committee_rules(committee):
	"""FR-M11-02.2, 02.3: ghi sổ vẫn thành công (mức Cảnh báo), báo từng mục và ghi Audit Log."""
	problems = committee_problems(committee)
	if not problems:
		return
	texts = [row["text"] for row in problems]
	frappe.msgprint(
		_("Committee warning: {0} The committee is still recorded.").format(" ".join(texts)),
		title=_("Committee warning"),
		indicator="orange",
	)
	codes = [row["code"] + (f":{row['group']}" if row["group"] else "") for row in problems]
	audit.log(
		"Update",
		COMMITTEE,
		committee.name,
		new={"committee_problems": codes},
		reason="IC_COMMITTEE_RULE_WARNING: " + ", ".join(codes),
	)


# FEAT-057: tên cũ giữ cho nơi gọi sẵn có
warn_missing_representatives = warn_committee_rules


def _committee_summary(committee, problems):
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
		"missing_representatives": [row["group"] for row in problems if row["code"] == "REPRESENTATIVE"],
		"problems": [
			{"code": row["code"], "text": row["text"], "blocking": row["blocking"]} for row in problems
		],
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
	if missing == ["member"]:
		return _("Missing network member")
	if missing == ["doctor"]:
		return _("Missing doctor")
	if missing == ["nurse"]:
		return _("Missing nurse/midwife/technician")
	return _("Missing doctor and nurse/midwife/technician")


def department_rows(network_rule=None):
	"""Mỗi khoa bắt buộc: số bác sĩ, số ĐD/HS/KTV đang hiệu lực và nhóm còn thiếu (BRU-ICP-003, FR-M11-03.3)."""
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
		if network_rule == NETWORK_ANY:
			missing = [] if doctors + nurses else ["member"]
		else:
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
		"people": extra.get("people") or [],
		"reasons": extra.get("reasons") or "",
	}


def _na(key, label):
	return _component(key, label, _("Not applicable (no inpatient care)"), "—", "na", _("Not applicable"))


def _committee_component(scale, settings, criteria, committee, problems):
	label = _("IC Committee")
	if scale == "outpatient":
		return _na("committee", label)
	current = _("{0}, {1} members").format(committee.name, len(committee.members)) if committee else "—"
	threshold = criteria["committee_min_beds"]
	if not _committee_required(scale, settings, criteria):
		return _component(
			"committee",
			label,
			_("Not required (under {0} beds)").format(threshold),
			current,
			"optional",
			_("Not required"),
		)
	requirement = (
		_("Required (≥ {0} beds)").format(threshold)
		if threshold
		else _("Required (every facility with inpatient care)")
	)
	if not committee:
		return _component(
			"committee", label, requirement, current, "missing", _("Missing", context="IC Structure"), 1
		)
	blocking = [row for row in problems if row["blocking"]]
	if blocking:
		missing = [row["group"] for row in blocking if row["code"] == "REPRESENTATIVE"]
		others = [row["text"] for row in blocking if row["code"] != "REPRESENTATIVE"]
		parts = [_("missing representative: {0}").format(", ".join(_(g) for g in missing))] if missing else []
		label_text = _("Present — {0}").format("; ".join(parts + others))
		return _component(
			"committee",
			label,
			requirement,
			current,
			"warning",
			label_text,
			reasons="; ".join(row["text"] for row in blocking),
		)
	return _component("committee", label, requirement, current, "ok", _("Sufficient"))


def _department_component(scale, settings):
	label = _("Infection Control Department") if scale == "large" else _("Infection Control Unit")
	if scale == "outpatient":
		return _na("ic_department", label)
	if settings.ic_department:
		name = frappe.db.get_value("Department", settings.ic_department, "department_name")
		return _component(
			"ic_department", label, _("Required"), name or settings.ic_department, "ok", _("Sufficient")
		)
	return _component(
		"ic_department", label, _("Required"), "—", "missing", _("Missing", context="IC Structure"), 1
	)


def _network_component(scale, departments, network_rule):
	label = _("IC Network")
	if scale == "outpatient":
		return _na("network", label)
	requirement = (
		_("Each department ≥ 1 network member")
		if network_rule == NETWORK_ANY
		else _("Each department ≥ 1 doctor + ≥ 1 nurse/midwife/technician")
	)
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
			"network",
			label,
			requirement,
			current,
			"missing",
			_("Missing {0} departments").format(missing),
			missing,
		)
	return _component("network", label, requirement, current, "ok", _("Sufficient"))


def _rounding_label(settings):
	return _("rounded down") if settings.get("surveillance_rounding") == ROUND_DOWN else _("rounded up")


def _surveillance_requirement(settings):
	ratio = cint(settings.surveillance_ratio_beds) or DEFAULT_RATIO
	required = required_surveillance(settings.bed_count, ratio, settings.get("surveillance_rounding"))
	text = _("≥ {0} people ({1} ÷ {2}, {3})").format(
		required, cint(settings.bed_count), ratio, _rounding_label(settings)
	)
	return required, text


def _count_status(key, label, requirement, required, actual, unverified=0, **extra):
	current = extra.pop("current", None) or _("{0} people").format(actual)
	shortfall = required - actual
	if shortfall <= 0:
		return _component(
			key, label, requirement, current, "ok", _("Sufficient"), required=required, actual=actual, **extra
		)
	if shortfall <= unverified:
		return _component(
			key,
			label,
			requirement,
			current,
			"unverified",
			_("Not verified", context="IC Structure"),
			required=required,
			actual=actual,
			**extra,
		)
	return _component(
		key,
		label,
		requirement,
		current,
		"missing",
		_("Missing {0}").format(shortfall),
		shortfall,
		required=required,
		actual=actual,
		**extra,
	)


def _surveillance_component(scale, settings):
	"""Chưa có bộ tiêu chí Đã duyệt: chỉ đếm người đang hiệu lực (chuyên trách khi có nội trú) như FEAT-057."""
	active = _active_staff(settings)
	if scale == "outpatient":
		label, required, actual = _("IC Person in Charge"), 1, len(active)
		requirement = _("≥ 1 person")
	elif scale == "small":
		label, required = _("Full-time IC Officer"), 1
		actual = sum(1 for row in active if cint(row.full_time))
		requirement = _("≥ 1 person")
	else:
		label = _("Full-time Surveillance Officers")
		required, requirement = _surveillance_requirement(settings)
		actual = sum(1 for row in active if cint(row.full_time))
	return _count_status("surveillance", label, requirement, required, actual)


# --- thành phần người theo bộ tiêu chí (FR-M11-01.5, 01.6; BRU-ICP-006, 007) -------------------------------------------


def _role_label(role, scale):
	if role == "Head":
		return _("Head of IC Department")
	if role == "Head Nurse":
		return _("Head Nurse of IC Department")
	if role == "Person in Charge":
		return _("IC Person in Charge") if scale == "outpatient" else _("IC Person in Charge (full-time)")
	return _("Full-time Surveillance Officers")


def _criteria_text(requirement):
	parts = []
	level = requirement.min_education or qualification.NO_EDUCATION
	if level != qualification.NO_EDUCATION:
		parts.append(_("{0} or higher").format(_(level)))
	if cint(requirement.health_field_required):
		parts.append(_("health field"))
	if cint(requirement.full_time_required):
		parts.append(_("full-time"))
	if cint(requirement.evidence_required):
		parts.append(_("IC certificate"))
	return ", ".join(parts)


PERSON_LABELS = {
	qualification.OK: ("Qualified", None),
	qualification.FAIL: ("Not met", "IC Structure"),
	qualification.UNVERIFIED: ("Not verified", "IC Structure"),
}


def _person_label(status):
	text, context = PERSON_LABELS[status]
	return _(text, context=context) if context else _(text)


def _role_requirements(profile, scale):
	by_role = {}
	for row in profile.role_requirements:
		if row.applies_to == scale.capitalize():
			by_role[row.ic_role] = row
		elif row.applies_to == "Any":
			by_role.setdefault(row.ic_role, row)
	return [(role, key, by_role[role]) for role, key in ROLE_KEYS if role in by_role]


def _people_components(scale, settings, criteria):
	counted = {}
	components = []
	for role, key, requirement in _role_requirements(criteria["profile"], scale):
		people = qualification.evaluate(_active_staff(settings, {role}), requirement)
		for person in people:
			if person["status"] != qualification.OK:
				continue
			earlier = counted.get(person["employee"])
			if earlier and not criteria["allow_both"]:
				person["status"] = qualification.FAIL
				person["reasons"] = [_("Already counted for role {0}").format(_role_label(earlier, scale))]
			else:
				counted.setdefault(person["employee"], role)
		for person in people:
			person["status_label"] = _person_label(person["status"])
		ok = sum(1 for person in people if person["status"] == qualification.OK)
		unverified = sum(1 for person in people if person["status"] == qualification.UNVERIFIED)
		if role == "Surveillance Officer" and scale == "large":
			required, requirement_text = _surveillance_requirement(settings)
		else:
			required, requirement_text = 1, _("≥ 1 person")
		criteria_text = _criteria_text(requirement)
		if criteria_text:
			requirement_text = f"{requirement_text} · {criteria_text}"
		reasons = "; ".join(
			"{}: {}".format(person["employee_name"] or person["employee"], ", ".join(person["reasons"]))
			for person in people
			if person["status"] != qualification.OK
		)
		components.append(
			_count_status(
				key,
				_role_label(role, scale),
				requirement_text,
				required,
				ok,
				unverified,
				current=_("{0} of {1} people qualified").format(ok, len(people)),
				people=people,
				reasons=reasons,
			)
		)
	return components


def _profile_summary(profile):
	if not profile:
		return None
	return {
		"name": profile.name,
		"profile_name": profile.profile_name,
		"version_no": cint(profile.version_no),
		"effective_from": str(profile.effective_from) if profile.effective_from else None,
		"legal_basis": profile.legal_basis,
	}


def compute():
	"""Bảng cơ cấu KSNK hiện tại (FR-M11-01): thành phần, khoa của mạng lưới, Hội đồng hiệu lực, bộ tiêu chí."""
	settings = frappe.get_single(SETTINGS)
	profile = structure_profile.active_profile()
	criteria = rules(profile)
	scale = _scale(settings, criteria)
	committee = active_committee()
	problems = committee_problems(committee, profile, settings) if committee else []
	departments = department_rows(criteria["network_rule"]) if scale != "outpatient" else []
	components = [
		_committee_component(scale, settings, criteria, committee, problems),
		_department_component(scale, settings),
		_network_component(scale, departments, criteria["network_rule"]),
	]
	if profile:
		components += _people_components(scale, settings, criteria)
	else:
		components.append(_surveillance_component(scale, settings))
	return {
		"scale": scale,
		"bed_count": cint(settings.bed_count),
		"components": components,
		"departments": departments,
		"committee": _committee_summary(committee, problems),
		"committee_required": _committee_required(scale, settings, criteria),
		"missing_total": sum(1 for row in components if row["status"] == "missing"),
		"profile": _profile_summary(profile),
		"profile_notice": None if profile else _("Structure criteria not approved"),
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
	duplicated = _duplicates((row.employee, row.ic_role) for row in doc.surveillance_staff if row.employee)
	if duplicated:
		frappe.throw(
			_("Employee {0} is listed more than once with the same role in IC staff.").format(
				", ".join(
					f"{employee} ({_(role, context='IC Surveillance Staff')})"
					for employee, role in duplicated
				)
			)
		)


def _check_committee(doc):
	if doc.valid_to and doc.valid_from and getdate(doc.valid_to) < getdate(doc.valid_from):
		frappe.throw(_("Valid To cannot be before Valid From."))
	duplicated = _duplicates(row.employee for row in doc.members if row.employee)
	if duplicated:
		frappe.throw(
			_("Employee {0} is listed more than once in the committee.").format(", ".join(duplicated))
		)
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
			_("The committee must have exactly one Chair and one Secretary: {0}.").format(
				"; ".join(problems)
			),
			title=_("Committee not complete"),
		)
	profile = structure_profile.active_profile()
	if not profile or profile.committee_rule_severity != BLOCK:
		return
	blocking = [row["text"] for row in committee_problems(doc, profile) if row["blocking"]]
	if blocking:
		frappe.throw(
			_("The committee does not meet the approved structure criteria: {0}").format(" ".join(blocking)),
			title=_("Committee not complete"),
		)


def _check_network_member(doc):
	if not cint(doc.is_active):
		return
	if frappe.db.exists(
		NETWORK,
		{
			"employee": doc.employee,
			"department": doc.department,
			"is_active": 1,
			"name": ["!=", doc.name or ""],
		},
	):
		frappe.throw(
			_("{0} is already an active network member of {1}.").format(doc.employee, doc.department)
		)


CHECKS = {SETTINGS: _check_settings, COMMITTEE: _check_committee, NETWORK: _check_network_member}


def check(doc, method=None):
	"""Validate hook ``infection_program.structure.check`` (FEAT-057, FEAT-094)."""
	handler = CHECKS.get(doc.doctype)
	if handler:
		handler(doc)
