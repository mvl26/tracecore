"""Kiểm điều kiện từng người của khoa/bộ phận KSNK theo vai trò (FEAT-094; FR-M11-01.5; BRU-ICP-006; OQ-V12-12, 14; A-138 g).

``evaluate(staff_rows, requirement, on)`` trả mỗi người ``{status: ok | fail | unverified, reasons}``; ``requirement`` là
một dòng ``IC Structure Role Requirement`` (tiêu chí là dữ liệu của bộ tiêu chí, không mã hóa cứng):

- ``full_time_required`` và dòng nhân sự không chuyên trách → Chưa đạt.
- yêu cầu bậc học hoặc khối ngành sức khỏe mà Employee chưa có ``tc_education_level`` → Chưa xác minh; bậc học dưới
  ``min_education`` hoặc không thuộc khối ngành sức khỏe → Chưa đạt.
- ``evidence_required``: ``Certificate`` loại được công nhận còn hiệu lực hôm nay, hoặc Training Result đạt của lớp
  ``Full-time IC Staff`` (FEAT-059). Chỉ có chứng chỉ được công nhận đã hết hiệu lực → Chưa đạt; chưa có gì → Chưa xác minh.

Chưa đạt thắng Chưa xác minh. ``training`` nhập trễ vì ``training`` đã nhập ``structure``.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

OK, FAIL, UNVERIFIED = "ok", "fail", "unverified"
EDUCATION_ORDER = ("Vocational", "College", "Bachelor", "Postgraduate")
NO_EDUCATION = "None"
EARLIEST = "2000-01-01"


def education_rank(level):
	return EDUCATION_ORDER.index(level) if level in EDUCATION_ORDER else -1


def _accepted_types(requirement, training):
	text = requirement.get("certificate_types") or ""
	own = {line.strip().casefold() for line in text.splitlines() if line.strip()}
	return own or training.accepted_certificate_types()


def _certificates(employees, accepted, on):
	"""{employee: "valid" | "invalid"} cho chứng chỉ thuộc loại được công nhận."""
	found = {}
	if not employees or not accepted:
		return found
	on = getdate(on)
	for row in frappe.get_all(
		"Certificate",
		filters={"employee": ["in", list(employees)]},
		fields=["employee", "certificate_type", "status", "issued_on", "no_expiry", "expires_on"],
	):
		if (row.certificate_type or "").strip().casefold() not in accepted:
			continue
		valid = (
			row.status == "Valid"
			and not (row.issued_on and getdate(row.issued_on) > on)
			and (cint(row.no_expiry) or (row.expires_on and getdate(row.expires_on) >= on))
		)
		if valid:
			found[row.employee] = "valid"
		else:
			found.setdefault(row.employee, "invalid")
	return found


def _employees(names):
	if not names:
		return {}
	return {
		row.name: row
		for row in frappe.get_all(
			"Employee",
			filters={"name": ["in", list(names)]},
			fields=["name", "employee_name", "tc_education_level", "tc_health_field"],
		)
	}


def _check(row, employee, requirement, evidence):
	fails, unverified = [], []
	if cint(requirement.get("full_time_required")) and not cint(row.full_time):
		fails.append(_("Not met: not full-time"))
	min_education = requirement.get("min_education") or NO_EDUCATION
	needs_education = min_education != NO_EDUCATION
	needs_health = cint(requirement.get("health_field_required"))
	level = employee.get("tc_education_level") if employee else None
	if (needs_education or needs_health) and not level:
		unverified.append(_("Not verified: no education level"))
	else:
		if needs_education and education_rank(level) < education_rank(min_education):
			fails.append(_("Not met: education below {0}").format(_(min_education)))
		if needs_health and not cint(employee.get("tc_health_field")):
			fails.append(_("Not met: not a health-field graduate"))
	if cint(requirement.get("evidence_required")):
		if evidence == "invalid":
			fails.append(_("Not met: IC certificate no longer valid"))
		elif evidence != "valid":
			unverified.append(_("Not verified: no IC certificate"))
	if fails:
		return FAIL, fails + unverified
	if unverified:
		return UNVERIFIED, unverified
	return OK, []


def evaluate(staff_rows, requirement, on=None):
	"""Danh sách người (theo thứ tự dòng) với trạng thái đạt / chưa đạt / chưa xác minh và lý do bằng chữ."""
	from tracecore.infection_program import training

	on = on or today()
	names = {row.employee for row in staff_rows if row.employee}
	employees = _employees(names)
	evidence = {}
	if cint(requirement.get("evidence_required")) and names:
		evidence = _certificates(names, _accepted_types(requirement, training), on)
		for name in training.passed_employees(EARLIEST, on, (training.CORE_STAFF,)) & names:
			evidence[name] = "valid"
	people = []
	for row in staff_rows:
		employee = employees.get(row.employee)
		status, reasons = _check(row, employee, requirement, evidence.get(row.employee))
		people.append(
			{
				"employee": row.employee,
				"employee_name": (employee.employee_name if employee else None) or row.employee_name,
				"status": status,
				"reasons": reasons,
			}
		)
	return people
