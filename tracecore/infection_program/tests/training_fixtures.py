"""Dữ liệu test đào tạo KSNK (FEAT-059): chương trình, lớp, kết quả HRMS Training, chứng chỉ, sinh viên thực tập."""

import frappe
from frappe.utils import add_days, get_datetime, today

COMPANY = "_Test Company"


def program(category, name=None):
	"""Training Program HRMS gắn `tc_ic_category` (A-135); trả tên."""
	name = name or f"KSNK {category or 'none'} {frappe.generate_hash(length=6)}"
	doc = frappe.get_doc(
		{
			"doctype": "Training Program",
			"training_program": name,
			"company": COMPANY,
			"description": "KSNK",
			"tc_ic_category": category,
		}
	)
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True).name


def event(training_program, on=None, employees=(), submit=True):
	"""Training Event (ngày `on`) có danh sách nhân viên; ghi sổ để Training Result nhận."""
	start = get_datetime(f"{on or today()} 08:00:00")
	doc = frappe.get_doc(
		{
			"doctype": "Training Event",
			"event_name": f"Lớp KSNK {frappe.generate_hash(length=6)}",
			"training_program": training_program,
			"event_status": "Completed",
			"type": "Seminar",
			"company": COMPANY,
			"location": "Hội trường",
			"start_time": start,
			"end_time": start.replace(hour=11),
			"introduction": "KSNK",
			"employees": [{"employee": emp, "attendance": "Present"} for emp in employees],
		}
	)
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc.name


def result(training_event, rows, submit=True):
	"""Training Result; `rows` là danh sách employee hoặc (employee, passed)."""
	employees = []
	for row in rows:
		emp, passed = row if isinstance(row, tuple) else (row, 1)
		employees.append({"employee": emp, "hours": 3, "tc_ic_passed": passed})
	doc = frappe.get_doc(
		{"doctype": "Training Result", "training_event": training_event, "employees": employees}
	)
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc.name


def trained(employees, category, on=None, passed=1, submit=True):
	"""Một lớp loại `category` đã có kết quả cho `employees`; trả tên Training Result."""
	training_event = event(program(category), on=on, employees=employees)
	return result(training_event, [(emp, passed) for emp in employees], submit=submit)


def certificate(employee, certificate_type, expires_on=None, no_expiry=0, status="Valid"):
	doc = frappe.get_doc(
		{
			"doctype": "Certificate",
			"employee": employee,
			"certificate_type": certificate_type,
			"certificate_no": frappe.generate_hash(length=8),
			"issued_on": add_days(today(), -30),
			"no_expiry": no_expiry,
			"expires_on": None if no_expiry else (expires_on or add_days(today(), 365)),
			"status": status,
		}
	)
	doc.flags.ignore_validate = True
	return doc.insert(ignore_permissions=True).name


def accept_certificates(*types):
	frappe.db.set_single_value("IC Program Settings", "ic_certificate_types", "\n".join(types))


def trainee(
	department, period_from=None, trained_on=None, result="Passed", full_name="SV Thực Tập", **fields
):
	return frappe.get_doc(
		{
			"doctype": "Trainee Induction",
			"full_name": full_name,
			"school": "ĐH Y Hà Nội",
			"department": department,
			"period_from": period_from or today(),
			"period_to": add_days(period_from or today(), 30),
			"trained_on": trained_on,
			"result": result,
			**fields,
		}
	).insert(ignore_permissions=True)
