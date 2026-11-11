"""Đào tạo KSNK trên HRMS Training và sinh viên thực tập (FEAT-059; FR-M11-09..11; UC-42; ADR-009; A-135).

- FR-M11-09: tỷ lệ nhân viên được đào tạo KSNK cơ bản trong năm theo khoa. Tử số = nhân viên đang làm việc có
  Training Result đã ghi sổ, dòng ``tc_ic_passed`` = 1, của lớp (Training Event đã ghi sổ, ngày bắt đầu trong kỳ) thuộc
  chương trình ``tc_ic_category`` = KSNK cơ bản; mẫu số = Employee ``Active`` của khoa (nghỉ việc không tính).
- FR-M11-10: giám sát viên chuyên trách, thành viên Hội đồng hiệu lực, mạng lưới viên hiệu lực (mỗi người đếm một
  lần) đạt khi có lớp đúng loại của nhóm mình trong kỳ hoặc ``Certificate`` thuộc danh sách
  ``IC Program Settings.ic_certificate_types`` còn hiệu lực tại ngày cuối kỳ (UC-42 A1).
- FR-M11-11: ``Trainee Induction`` — ``status`` Hợp lệ / Chưa đào tạo / Muộn hơn ngày bắt đầu; muộn thì cảnh báo, vẫn lưu.

Kỳ ``YYYY-MM`` của M9 tính cộng dồn từ đầu năm tới cuối tháng (sinh viên: các đợt bắt đầu trong tháng). Hàm chỉ số
đăng ký qua hook ``tracecore_ic_indicators`` (``register``); M9 không import module này.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, get_last_day, getdate

from tracecore.core import notification
from tracecore.infection_program import structure

SETTINGS = structure.SETTINGS
NETWORK = structure.NETWORK
TRAINEE = "Trainee Induction"
SCREEN_SLUG = "dao-tao"
REMINDER_EVENT = "IC_TRAINING_REMINDER"

# Training Program.tc_ic_category (architecture §5.3.1)
BASIC = "Basic IC"
CORE_STAFF = "Full-time IC Staff"
COMMITTEE_NETWORK = "Committee and Network"
NEW_STAFF = "New Staff"
CATEGORIES = (BASIC, CORE_STAFF, COMMITTEE_NETWORK, NEW_STAFF)
# nhóm đối tượng FR-M11-10 → loại lớp đúng quy định (A-135 b)
GROUP_CATEGORY = {"full_time": CORE_STAFF, "committee": COMMITTEE_NETWORK, "network": COMMITTEE_NETWORK}
GROUP_LABELS = {
	"full_time": "Full-time IC staff",
	"committee": "Committee member",
	"network": "Network member",
}

TRAINEE_VALID, TRAINEE_NOT_TRAINED, TRAINEE_LATE = "Valid", "Not Trained", "Trained After Start"
TRAINEE_STATUSES = (TRAINEE_VALID, TRAINEE_NOT_TRAINED, TRAINEE_LATE)

KEY_BASIC = "IC_TRAINING_BASIC"
KEY_CORE = "IC_TRAINING_CORE"
KEY_TRAINEE = "IC_TRAINEE_INDUCTION"


# --- kỳ, tỷ lệ ----------------------------------------------------------------------------------------------------


def check_year(year):
	value = cint(year)
	if not 2000 <= value <= 2100:
		frappe.throw(_("Enter a valid year."), frappe.ValidationError)
	return value


def year_range(year):
	year = check_year(year)
	return getdate(f"{year}-01-01"), getdate(f"{year}-12-31")


def period_start(period):
	return getdate(f"{period}-01")


def year_to_date(period):
	"""Kỳ tháng ``YYYY-MM`` → (01/01 của năm, ngày cuối tháng)."""
	start = period_start(period)
	return start.replace(month=1, day=1), get_last_day(start)


def rate(numerator, denominator):
	"""Tỷ lệ %, 1 chữ số thập phân; mẫu số 0 → None ("Không tính", BRU-RPT-001)."""
	return round(flt(numerator) * 100 / denominator, 1) if denominator else None


def rate_label(value):
	return "—" if value is None else f"{value:.1f}".replace(".", ",") + " %"


def rate_status(value, target):
	"""(mã, nhãn đã dịch) của tỷ lệ so với mục tiêu: ``na`` / ``none`` / ``ok`` / ``below``."""
	if value is None:
		return "na", _("Not calculated")
	if not target:
		return "none", _("No target")
	if value >= flt(target):
		return "ok", _("Met", context="IC Training")
	return "below", _("Below target")


def basic_target():
	"""Mục tiêu (%) của chỉ số đào tạo cơ bản trong danh mục IC Indicator do R01 duyệt; chưa có → None."""
	target = frappe.db.get_value(
		"IC Indicator", {"source_method": KEY_BASIC, "is_active": 1}, "national_target"
	)
	return flt(target) or None


def _summary(numerator, denominator):
	value = rate(numerator, denominator)
	return {"rate": value, "rate_label": rate_label(value)}


# --- HRMS Training ------------------------------------------------------------------------------------------------


def passed_employees(start, end, categories):
	"""Nhân viên có Training Result đạt (đã ghi sổ, ``tc_ic_passed``) của lớp loại ``categories`` bắt đầu trong kỳ."""
	if not categories:
		return set()
	rows = frappe.db.sql(
		"""
		select distinct tre.employee
		from `tabTraining Result Employee` tre
		join `tabTraining Result` tr on tr.name = tre.parent and tre.parenttype = 'Training Result'
		join `tabTraining Event` te on te.name = tr.training_event
		join `tabTraining Program` tp on tp.name = te.training_program
		where tr.docstatus = 1 and te.docstatus = 1 and tre.tc_ic_passed = 1
			and tp.tc_ic_category in %(categories)s
			and date(te.start_time) between %(start)s and %(end)s
		""",
		{"categories": tuple(categories), "start": start, "end": end},
	)
	return {row[0] for row in rows if row[0]}


def untagged_events(start, end):
	"""Số lớp đã ghi sổ trong kỳ không thuộc chương trình có loại KSNK — không vào tử số (UC-42 E2)."""
	return cint(
		frappe.db.sql(
			"""
			select count(*) from `tabTraining Event` te
			left join `tabTraining Program` tp on tp.name = te.training_program
			where te.docstatus = 1 and date(te.start_time) between %(start)s and %(end)s
				and ifnull(tp.tc_ic_category, '') = ''
			""",
			{"start": start, "end": end},
		)[0][0]
	)


def active_employees(end, department=None):
	"""Employee đang làm việc (``Active``), đã vào làm trước ngày cuối kỳ, có khoa (FR-M11-09.2)."""
	return frappe.get_all(
		"Employee",
		filters={"status": "Active", "department": department or ["is", "set"]},
		or_filters=[["date_of_joining", "is", "not set"], ["date_of_joining", "<=", end]],
		fields=["name as employee", "employee_name", "department", "user_id"],
		order_by="employee_name asc",
		limit_page_length=0,
	)


def _department_names(names):
	if not names:
		return {}
	return dict(
		frappe.get_all(
			"Department",
			filters={"name": ["in", list(names)]},
			fields=["name", "department_name"],
			as_list=True,
		)
	)


def _wards(department=None):
	filters = {"tc_is_ward": 1, "disabled": 0, "is_group": 0}
	if department:
		filters["name"] = department
	return frappe.get_all("Department", filters=filters, pluck="name")


# --- FR-M11-09 ----------------------------------------------------------------------------------------------------


def _basic(start, end, department=None):
	staff = active_employees(end, department)
	passed = passed_employees(start, end, (BASIC,))
	by_department: dict[str, list] = {name: [] for name in _wards(department)}
	for row in staff:
		by_department.setdefault(row.department, []).append(row)
	names = _department_names(by_department)
	target = basic_target()
	rows = []
	for name, people in by_department.items():
		untrained = [row for row in people if row.employee not in passed]
		value = rate(len(people) - len(untrained), len(people))
		status, label = rate_status(value, target)
		rows.append(
			{
				"department": name,
				"department_name": names.get(name) or name,
				"employees": len(people),
				"trained": len(people) - len(untrained),
				"rate": value,
				"rate_label": rate_label(value),
				"status": status,
				"status_label": label,
				"untrained": [dict(row) for row in untrained],
			}
		)
	rows.sort(key=lambda row: (row["department_name"] or "").lower())
	employees = sum(row["employees"] for row in rows)
	trained = sum(row["trained"] for row in rows)
	total = {"employees": employees, "trained": trained, **_summary(trained, employees)}
	total["status"], total["status_label"] = rate_status(total["rate"], target)
	return {
		"departments": rows,
		"total": total,
		"target": target,
		"untagged_events": untagged_events(start, end),
	}


def basic_rows(year, department=None):
	"""SCR-49 / Script Report: tỷ lệ đào tạo KSNK cơ bản theo khoa trong năm, kèm danh sách chưa học."""
	start, end = year_range(year)
	return _basic(start, end, department)


def basic_rate(period, department=None):
	"""Chỉ số ``IC_TRAINING_BASIC`` (FR-M11-09): (đã đào tạo, nhân viên đang làm việc, cỡ mẫu)."""
	start, end = year_to_date(period)
	total = _basic(start, end, department)["total"]
	return total["trained"], total["employees"], total["employees"]


# --- FR-M11-10 ----------------------------------------------------------------------------------------------------


def core_targets(on):
	"""{employee: {nhóm}} của giám sát viên chuyên trách, Hội đồng hiệu lực và mạng lưới viên đang hiệu lực."""
	targets: dict[str, set] = {}
	for row in frappe.get_single(SETTINGS).get("surveillance_staff") or []:
		if cint(row.full_time) and cint(row.is_active) and row.employee:
			targets.setdefault(row.employee, set()).add("full_time")
	committee = structure.active_committee(on)
	for row in committee.members if committee else []:
		if row.employee:
			targets.setdefault(row.employee, set()).add("committee")
	for employee in frappe.get_all(NETWORK, filters={"is_active": 1}, pluck="employee"):
		if employee:
			targets.setdefault(employee, set()).add("network")
	return targets


def accepted_certificate_types():
	text = frappe.db.get_single_value(SETTINGS, "ic_certificate_types") or ""
	return {line.strip().casefold() for line in text.splitlines() if line.strip()}


def certified_employees(employees, on):
	"""Nhân viên có Certificate loại KSNK được công nhận còn hiệu lực tại ngày ``on`` (FR-M4-02, A-135 b)."""
	accepted = accepted_certificate_types()
	if not accepted or not employees:
		return set()
	on = getdate(on)
	certified = set()
	for row in frappe.get_all(
		"Certificate",
		filters={"employee": ["in", list(employees)], "status": "Valid"},
		fields=["employee", "certificate_type", "issued_on", "no_expiry", "expires_on"],
	):
		if (row.certificate_type or "").strip().casefold() not in accepted:
			continue
		if row.issued_on and getdate(row.issued_on) > on:
			continue
		if cint(row.no_expiry) or (row.expires_on and getdate(row.expires_on) >= on):
			certified.add(row.employee)
	return certified


def _core(start, end, department=None):
	targets = core_targets(end)
	staff = {}
	if targets:
		filters = {"name": ["in", list(targets)], "status": "Active"}
		if department:
			filters["department"] = department
		staff = {
			row.name: row
			for row in frappe.get_all(
				"Employee", filters=filters, fields=["name", "employee_name", "department"]
			)
		}
	certified = certified_employees(staff, end)
	passed_by_category = {
		category: passed_employees(start, end, (category,)) for category in set(GROUP_CATEGORY.values())
	}
	names = _department_names({row.department for row in staff.values() if row.department})
	people = []
	for employee, row in staff.items():
		groups = sorted(targets[employee])
		trained = any(employee in passed_by_category[GROUP_CATEGORY[group]] for group in groups)
		basis = "training" if trained else ("certificate" if employee in certified else None)
		people.append(
			{
				"employee": employee,
				"employee_name": row.employee_name,
				"department": row.department,
				"department_name": names.get(row.department) or row.department or "",
				"groups": groups,
				"group_labels": [_(GROUP_LABELS[group]) for group in groups],
				"passed": basis is not None,
				"basis": basis,
			}
		)
	people.sort(key=lambda row: (row["passed"], (row["employee_name"] or "").lower()))
	passed = sum(1 for row in people if row["passed"])
	return {
		"people": people,
		"total": {"passed": passed, "people": len(people), **_summary(passed, len(people))},
	}


def core_rows(year, department=None):
	start, end = year_range(year)
	return _core(start, end, department)


def core_rate(period, department=None):
	"""Chỉ số ``IC_TRAINING_CORE`` (FR-M11-10): (đạt, số người thuộc diện, cỡ mẫu)."""
	start, end = year_to_date(period)
	total = _core(start, end, department)["total"]
	return total["passed"], total["people"], total["people"]


# --- FR-M11-11 ----------------------------------------------------------------------------------------------------


def trainee_status(trained_on, period_from):
	if not trained_on:
		return TRAINEE_NOT_TRAINED
	return TRAINEE_LATE if getdate(trained_on) > getdate(period_from) else TRAINEE_VALID


def validate_trainee(doc):
	"""Controller Trainee Induction: kiểm kỳ thực tập, tính ``status``, cảnh báo đào tạo muộn (FR-M11-11.1)."""
	if doc.period_from and doc.period_to and getdate(doc.period_to) < getdate(doc.period_from):
		frappe.throw(_("Internship end date cannot be before the start date."))
	doc.status = trainee_status(doc.trained_on, doc.period_from)
	if doc.status == TRAINEE_LATE:
		frappe.msgprint(
			_(
				"Infection control training on {0} is later than the internship start date {1}. The record is saved as trained after start; move the training date or the start date."
			).format(formatdate(doc.trained_on, "dd/MM/yyyy"), formatdate(doc.period_from, "dd/MM/yyyy")),
			title=_("Trained after start"),
			indicator="orange",
		)


def _trainees(start, end, department=None):
	filters = {"period_from": ["between", [start, end]]}
	if department:
		filters["department"] = department
	return frappe.get_all(
		TRAINEE,
		filters=filters,
		fields=[
			"name",
			"school",
			"department",
			"department_name",
			"period_from",
			"trained_on",
			"result",
			"status",
		],
		order_by="period_from desc, name desc",
	)


def trainee_rows(year, department=None):
	start, end = year_range(year)
	rows = _trainees(start, end, department)
	for row in rows:
		row["status_label"] = _(row.status, context=TRAINEE)
	return {
		"rows": rows,
		"late": sum(1 for row in rows if row.status == TRAINEE_LATE),
		"not_trained": sum(1 for row in rows if row.status == TRAINEE_NOT_TRAINED),
	}


def trainee_rate(period, department=None):
	"""Chỉ số ``IC_TRAINEE_INDUCTION`` (FR-M11-11): sinh viên đào tạo đúng hạn và đạt / sinh viên bắt đầu trong tháng."""
	start = period_start(period)
	rows = _trainees(start, get_last_day(start), department)
	passed = sum(1 for row in rows if row.status == TRAINEE_VALID and row.result == "Passed")
	return passed, len(rows), len(rows)


# --- nhắc, hook ---------------------------------------------------------------------------------------------------


def remind(department, year):
	"""Gửi ``IC_TRAINING_REMINDER`` cho user của nhân viên khoa chưa học KSNK cơ bản trong năm (UC-42 A2)."""
	rows = basic_rows(year, department)["departments"]
	untrained = [person for row in rows if row["department"] == department for person in row["untrained"]]
	users = [person["user_id"] for person in untrained if person.get("user_id")]
	sent = []
	if users:
		sent = notification.emit(
			REMINDER_EVENT,
			subject=_("Infection control training reminder"),
			message=_(
				"You have not completed the basic infection control training in {0}. Please join the next class."
			).format(check_year(year)),
			users=users,
			link="/app/training-event",
		)
	return {
		"untrained": len(untrained),
		"sent": len(sent or []),
		"without_account": len(untrained) - len(users),
	}


def register():
	"""Hook ``tracecore_ic_indicators``: hàm tính chỉ số đào tạo KSNK cho bảng chỉ số M9."""
	return {KEY_BASIC: basic_rate, KEY_CORE: core_rate, KEY_TRAINEE: trainee_rate}
