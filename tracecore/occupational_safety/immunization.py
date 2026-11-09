"""Tiêm chủng nhân viên (FEAT-071; FR-M16-07, FR-M16-07.1; BRU-OCC-004; A-137 f, g).

`next_due` = ngày tiêm + khoảng giữa mũi khi còn thiếu mũi, + khoảng nhắc lại khi đã đủ (0 = không nhắc). Nhắc nhân
viên và R02 theo mức 60/30/7 ngày/quá hạn, mỗi mức một lần, như FR-M4-01.4 (M16 không import `tracecore.hr`).
Tỷ lệ bao phủ: chỉ yêu cầu Approved, mẫu số là nhân viên `Active` thuộc khoa hoặc chức danh có nguy cơ.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, getdate, today

from tracecore.core import notification
from tracecore.occupational_safety import config

DOCTYPE = "Staff Immunization"
THRESHOLDS = (60, 30, 7)
EXPIRED = -1
RANK = {0: 0, 60: 1, 30: 2, 7: 3, EXPIRED: 4}


def level_for(days_left):
	if days_left < 0:
		return EXPIRED
	for threshold in sorted(THRESHOLDS):
		if days_left <= threshold:
			return threshold
	return 0


def is_due(level, sent):
	return level != 0 and RANK[level] > RANK.get(cint(sent), 0)


def next_due(requirement, dose_no, given_on):
	given = getdate(given_on)
	if cint(dose_no) < cint(requirement.doses_required) and cint(requirement.dose_interval_days):
		return add_days(given, cint(requirement.dose_interval_days))
	if cint(dose_no) >= cint(requirement.doses_required) and cint(requirement.booster_interval_days):
		return add_days(given, cint(requirement.booster_interval_days))
	return None


def validate(doc):
	if cint(doc.dose_no) < 1:
		frappe.throw(_("Dose number must be at least 1."), frappe.ValidationError)
	if getdate(doc.given_on) > getdate(today()):
		frappe.throw(_("The vaccination date cannot be in the future."), frappe.ValidationError)
	requirement = frappe.get_doc(config.REQUIREMENT, doc.vaccine)
	due = next_due(requirement, doc.dose_no, doc.given_on)
	if not doc.is_new() and str(getdate(doc.next_due) if doc.next_due else None) != str(due):
		doc.reminded_level = 0
	doc.next_due = due


def _latest_doses():
	"""Mũi mới nhất của mỗi (nhân viên, vaccine): chỉ mũi này quyết định hạn kế tiếp."""
	rows = frappe.get_all(
		DOCTYPE,
		fields=["name", "employee", "vaccine", "dose_no", "given_on", "next_due", "reminded_level"],
		order_by="given_on desc, dose_no desc, creation desc",
	)
	latest = {}
	for row in rows:
		latest.setdefault((row.employee, row.vaccine), row)
	return list(latest.values())


def remind_due(day=None):
	"""Nhắc nhân viên + R02 (Rule mặc định) khi mũi kế tiếp tới mức 60/30/7 ngày hoặc quá hạn; trả số lần nhắc."""
	day = getdate(day or today())
	sent = 0
	for row in _latest_doses():
		if not row.next_due:
			continue
		if frappe.db.get_value("Employee", row.employee, "status") != "Active":
			continue
		level = level_for(date_diff(row.next_due, day))
		if not is_due(level, row.reminded_level):
			continue
		frappe.db.set_value(DOCTYPE, row.name, "reminded_level", level, update_modified=False)
		user = frappe.db.get_value("Employee", row.employee, "user_id")
		subject = (
			_("Vaccination {0} is overdue since {1}").format(row.vaccine, frappe.format(row.next_due, "Date"))
			if level == EXPIRED
			else _("Vaccination {0} is due on {1}").format(row.vaccine, frappe.format(row.next_due, "Date"))
		)
		notification.emit(
			"IMMUNIZATION_DUE",
			frappe._dict(doctype=DOCTYPE, name=row.name),
			subject=subject,
			users=[user] if user else [],
		)
		sent += 1
	return sent


def _at_risk(requirement):
	departments = [row.department for row in requirement.departments]
	designations = [row.designation for row in requirement.designations]
	if not departments and not designations:
		return set()
	or_filters = []
	if departments:
		or_filters.append(["department", "in", departments])
	if designations:
		or_filters.append(["designation", "in", designations])
	return set(frappe.get_all("Employee", filters={"status": "Active"}, or_filters=or_filters, pluck="name"))


def _covered(requirement, employees, day):
	if not employees:
		return set()
	covered = set()
	for row in frappe.get_all(
		DOCTYPE,
		filters={"vaccine": requirement.name, "employee": ["in", list(employees)]},
		fields=["employee", "dose_no", "next_due", "given_on"],
		order_by="given_on desc, dose_no desc",
	):
		if row.employee in covered:
			continue
		if cint(row.dose_no) >= cint(requirement.doses_required) and (
			not row.next_due or getdate(row.next_due) >= day
		):
			covered.add(row.employee)
	return covered


def coverage(department=None, day=None):
	"""FR-M16-07: tỷ lệ bao phủ từng vaccine và tỷ lệ nhân viên đủ mọi mũi bắt buộc (07.1: nghỉ việc không tính)."""
	day = getdate(day or today())
	per_vaccine = []
	risk_all, missing = set(), set()
	for requirement in config.approved_requirements():
		employees = _at_risk(requirement)
		if department:
			employees &= set(frappe.get_all("Employee", filters={"department": department}, pluck="name"))
		covered = _covered(requirement, employees, day)
		risk_all |= employees
		missing |= employees - covered
		per_vaccine.append(
			{
				"vaccine": requirement.name,
				"at_risk": len(employees),
				"covered": len(covered),
				"rate": round(100.0 * len(covered) / len(employees), 1) if employees else None,
			}
		)
	fully = len(risk_all - missing)
	return {
		"vaccines": per_vaccine,
		"at_risk": len(risk_all),
		"fully_covered": fully,
		"rate": round(100.0 * fully / len(risk_all), 1) if risk_all else None,
	}
