"""Dữ liệu test dùng chung cho cơ cấu KSNK (FEAT-057): khoa bắt buộc mạng lưới, nhân viên, mạng lưới viên, Hội đồng."""

import frappe
from frappe.utils import add_days, today

from tracecore.tests import factories

SETTINGS = "IC Program Settings"


def required_department(name):
	"""Khoa có cờ `tc_ic_network_required` (A-132 c); trả tên Department."""
	department = factories.make_department(name)
	frappe.db.set_value("Department", department, "tc_ic_network_required", 1)
	return department


def clear_required_departments():
	"""Bỏ cờ bắt buộc của khoa có sẵn trên site test để test chỉ thấy khoa của mình (rollback theo savepoint)."""
	frappe.db.sql("update `tabDepartment` set tc_ic_network_required = 0")


def employee(first_name, department=None, user=None):
	fields = {"user_id": user} if user else {}
	return factories.make_employee(first_name=first_name, department=department, **fields).name


def network_member(employee_name, department, member_type="Doctor", is_active=1):
	return frappe.get_doc(
		{
			"doctype": "IC Network Member",
			"employee": employee_name,
			"department": department,
			"member_type": member_type,
			"appointed_on": today(),
			"decision_no": "01/QĐ-BV",
			"is_active": is_active,
		}
	).insert(ignore_permissions=True)


def settings(bed_count=420, has_inpatient=1, ratio=150, ic_department=None, staff=()):
	"""Ghi IC Program Settings; `staff` là danh sách (employee, full_time, is_active)."""
	doc = frappe.get_single(SETTINGS)
	doc.update(
		{
			"bed_count": bed_count,
			"facility_level": "Specialized Level",
			"has_inpatient": has_inpatient,
			"surveillance_ratio_beds": ratio,
			"doc_review_months": 12,
			"ic_department": ic_department,
		}
	)
	doc.set("surveillance_staff", [])
	for employee_name, full_time, is_active in staff:
		doc.append("surveillance_staff", {"employee": employee_name, "full_time": full_time, "is_active": is_active})
	doc.save(ignore_permissions=True)
	return doc


def committee(members, valid_from=None, valid_to=None, submit=False):
	"""`members` là danh sách (employee, committee_role, representing)."""
	doc = frappe.get_doc(
		{
			"doctype": "IC Committee",
			"decision_no": "152/QĐ-BV",
			"decision_date": valid_from or today(),
			"valid_from": valid_from or today(),
			"valid_to": valid_to,
			"members": [
				{"employee": emp, "committee_role": role, "representing": representing}
				for emp, role, representing in members
			],
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def full_committee_members(prefix="HD"):
	"""Đủ Chủ tịch, Thư ký và 3 khối đại diện bắt buộc."""
	return [
		(employee(f"{prefix} Chair"), "Chair", "Functional Unit"),
		(employee(f"{prefix} Secretary"), "Secretary", "Functional Unit"),
		(employee(f"{prefix} Micro"), "Ordinary Member", "Microbiology and Laboratory"),
		(employee(f"{prefix} Pharma"), "Ordinary Member", "Pharmacy"),
		(employee(f"{prefix} ICU"), "Ordinary Member", "High-risk Clinical"),
	]


def yesterday():
	return add_days(today(), -1)
