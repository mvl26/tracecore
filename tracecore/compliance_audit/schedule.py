"""Lịch giám sát `Audit Schedule`: kỳ, độ bao phủ, giao việc và nhắc tuần cuối kỳ (FEAT-060; FR-M12-03, UC-43).

Độ bao phủ tính lúc đọc từ phiếu đã ghi sổ trong kỳ, theo mã mẫu (mọi phiên bản) x khoa: số phiếu, hoặc số cơ hội với
mẫu "By Opportunity" (vệ sinh tay). Không có DocType "việc": giao việc = thông báo ``AUDIT_DUE`` ngày đầu kỳ cho người
phụ trách; tuần cuối kỳ khoa chưa đạt mục tiêu → ``AUDIT_COVERAGE_LOW`` cho người phụ trách và R02 (theo Rule).
Mỗi kỳ gửi mỗi loại một lần (``last_due_period``, ``last_low_period``).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_first_day, get_last_day, getdate

from tracecore.compliance_audit import templates
from tracecore.core import notification

DOCTYPE = "Audit Schedule"
SESSION = "Audit Session"
WEEKLY, MONTHLY, QUARTERLY = "Weekly", "Monthly", "Quarterly"
LAST_WEEK_DAYS = 7


def period_of(frequency, on=None):
	"""(ngày đầu, ngày cuối, khóa kỳ) của kỳ chứa ngày ``on``: tuần ISO, tháng hoặc quý."""
	on = getdate(on)
	if frequency == WEEKLY:
		start = add_days(on, -on.weekday())
		year, week, _day = on.isocalendar()
		return getdate(start), getdate(add_days(start, 6)), f"{year}-W{week:02d}"
	if frequency == QUARTERLY:
		quarter = (on.month - 1) // 3
		start = on.replace(month=quarter * 3 + 1, day=1)
		return start, get_last_day(start.replace(month=quarter * 3 + 3)), f"{on.year}-Q{quarter + 1}"
	return get_first_day(on), get_last_day(on), on.strftime("%Y-%m")


def validate(doc):
	"""Gọi từ ``AuditSchedule.validate``."""
	if frappe.db.get_value(templates.DOCTYPE, doc.audit_template, "docstatus") != 1:
		frappe.throw(
			_("Template {0} is not approved. Only approved templates can be scheduled.").format(
				doc.audit_template
			)
		)
	if cint(doc.target_count) <= 0:
		frappe.throw(_("Target per department must be greater than 0."))
	seen = set()
	for row in doc.departments:
		if row.department in seen:
			frappe.throw(_("Department {0} is listed twice.").format(row.department))
		seen.add(row.department)
	if not seen:
		frappe.throw(_("Add at least one department."))


def _done(template_code, departments, start, end):
	"""{khoa: số phiếu (hoặc số cơ hội vệ sinh tay)} đã ghi sổ trong kỳ."""
	if not departments:
		return {}
	by_opportunity = (
		frappe.db.get_value(templates.DOCTYPE, {"template_code": template_code}, "scoring_method")
		== templates.BY_OPPORTUNITY
	)
	session = frappe.qb.DocType(SESSION)
	query = (
		frappe.qb.from_(session)
		.where(session.template_code == template_code)
		.where(session.docstatus == 1)
		.where(session.department.isin(list(departments)))
		.where(session.audit_date[start:end])
		.groupby(session.department)
	)
	if by_opportunity:
		opportunity = frappe.qb.DocType("Hand Hygiene Opportunity")
		query = query.join(opportunity).on(
			(opportunity.parent == session.name) & (opportunity.parenttype == SESSION)
		)
		count = frappe.query_builder.functions.Count(opportunity.name)
	else:
		count = frappe.query_builder.functions.Count(session.name)
	return {row[0]: row[1] for row in query.select(session.department, count).run()}


def coverage(name, on=None):
	"""Độ bao phủ kỳ hiện tại (hoặc kỳ chứa ``on``) theo khoa: ``[{department, done, target, label, period}]``."""
	doc = frappe.get_doc(DOCTYPE, name) if isinstance(name, str) else name
	start, end, key = period_of(doc.frequency, on)
	departments = [row.department for row in doc.departments]
	done = _done(doc.template_code, departments, start, end)
	target = cint(doc.target_count)
	return [
		{
			"department": department,
			"done": cint(done.get(department)),
			"target": target,
			"label": f"{cint(done.get(department))}/{target}",
			"period": key,
		}
		for department in departments
	]


def _user_of(employee):
	return frappe.db.get_value("Employee", employee, "user_id") if employee else None


def _in_last_week(frequency, on, end):
	if frequency == WEEKLY:
		return on == end
	return on > add_days(end, -LAST_WEEK_DAYS)


def run_daily(on=None):
	"""Scheduler hằng ngày: giao việc ngày đầu kỳ, nhắc tuần cuối kỳ khoa chưa đạt mục tiêu."""
	on = getdate(on)
	for name in frappe.get_all(DOCTYPE, filters={"active": 1}, pluck="name"):
		doc = frappe.get_doc(DOCTYPE, name)
		if frappe.db.get_value(templates.DOCTYPE, doc.audit_template, "docstatus") != 1:
			continue
		start, end, key = period_of(doc.frequency, on)
		user = _user_of(doc.assignee)
		if on == start and doc.last_due_period != key:
			notification.emit(
				"AUDIT_DUE",
				doc,
				subject=_("Audits due: {0} ({1})").format(doc.template_title or doc.template_code, key),
				message=_("Target {0} per department for {1} departments in period {2}.").format(
					doc.target_count, len(doc.departments), key
				),
				users=[user] if user else (),
			)
			doc.db_set("last_due_period", key, update_modified=False)
		if _in_last_week(doc.frequency, on, end) and doc.last_low_period != key:
			low = [row for row in coverage(doc, on) if row["done"] < row["target"]]
			if low:
				notification.emit(
					"AUDIT_COVERAGE_LOW",
					doc,
					subject=_("Audit coverage below target: {0} ({1})").format(
						doc.template_title or doc.template_code, key
					),
					message="; ".join(f"{row['department']}: {row['label']}" for row in low),
					users=[user] if user else (),
				)
			doc.db_set("last_low_period", key, update_modified=False)
