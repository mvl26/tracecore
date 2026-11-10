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
	"""Ghi IC Program Settings; `staff` là danh sách (employee, full_time, is_active[, ic_role]) — FEAT-094 thêm vai trò."""
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
	for employee_name, full_time, is_active, *role in staff:
		row = {"employee": employee_name, "full_time": full_time, "is_active": is_active}
		if role:
			row["ic_role"] = role[0]
		doc.append("surveillance_staff", row)
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


# --- FEAT-058: kế hoạch năm, văn bản nội bộ, họp Hội đồng --------------------------------------------------------


def user(code, prefix="ksnk-plan"):
	"""User có Role `TC <code>` (R01, R13…)."""
	return factories.make_user(f"{prefix}-{code.lower()}@example.com", [f"TC {code}"])


def indicator(code, kind="Percentage", direction="Higher is better", target=80, min_sample=0):
	if not frappe.db.exists("IC Indicator", code):
		frappe.get_doc(
			{
				"doctype": "IC Indicator",
				"code": code,
				"indicator_name": f"Indicator {code}",
				"measure_group": "Hand Hygiene",
				"kind": kind,
				"target_direction": direction,
				"national_target": target,
				"min_sample": min_sample,
			}
		).insert(ignore_permissions=True)
	return code


def indicator_value(code, period, numerator, denominator, locked=1, department=None):
	frappe.get_doc(
		{
			"doctype": "IC Indicator Value",
			"indicator": code,
			"period": period,
			"department": department,
			"numerator": numerator,
			"denominator": denominator,
			"sample_size": denominator,
			"value": numerator / denominator * 100 if denominator else 0,
			"sample_note": "" if denominator else "Not calculated",
			"locked": locked,
		}
	).insert(ignore_permissions=True)


def clear_plans(year):
	"""Bỏ kế hoạch có sẵn trên site test cho năm `year` (rollback theo savepoint của IsolatedTestCase)."""
	for table in ("IC Plan Activity", "IC Plan Indicator"):
		frappe.db.sql(
			f"delete c from `tab{table}` c join `tabIC Annual Plan` p on p.name = c.parent where p.year = %s",
			year,
		)
	frappe.db.sql("delete from `tabIC Annual Plan` where year = %s", year)


def plan(year, indicators=(), activities=(), objectives="Reduce HAI"):
	"""Kế hoạch Nháp; `indicators` là (mã, nền, mục tiêu), `activities` là dict trường của IC Plan Activity."""
	return frappe.get_doc(
		{
			"doctype": "IC Annual Plan",
			"year": year,
			"objectives": objectives,
			"indicators": [
				{"indicator": code, "baseline": baseline, "target": target}
				for code, baseline, target in indicators
			],
			"activities": [
				{"measure_group": "Hand Hygiene", "budget_vnd": 1000000, **activity}
				for activity in activities
			],
		}
	).insert(ignore_permissions=True)


def approve(doc, approver):
	"""R13 ghi sổ qua ``annual_plan.approve`` (đường của RPC và nút trên form)."""
	from tracecore.infection_program import annual_plan

	previous = frappe.session.user
	frappe.set_user(approver)
	try:
		annual_plan.approve(doc.name)
	finally:
		frappe.set_user(previous)
	return frappe.get_doc(doc.doctype, doc.name)


def procedure(
	doc_code, title="Hand hygiene procedure", issued_on=None, review_due=None, version_no=1, **values
):
	return frappe.get_doc(
		{
			"doctype": "IC Procedure Document",
			"doc_code": doc_code,
			"title": title,
			"doc_type": "Procedure",
			"version_no": version_no,
			"measure_group": "Hand Hygiene",
			"issued_on": issued_on or today(),
			"review_due": review_due,
			**values,
		}
	).insert(ignore_permissions=True)


def meeting(resolutions=(), attendees=(), meeting_date=None, submit=False):
	"""`resolutions` là (nội dung, employee, hạn); `attendees` là danh sách employee."""
	doc = frappe.get_doc(
		{
			"doctype": "IC Committee Meeting",
			"meeting_date": meeting_date or today(),
			"agenda": "Quarterly review",
			"attendees": [{"employee": emp} for emp in attendees],
			"resolutions": [
				{"content": content, "responsible": emp, "due_date": due} for content, emp, due in resolutions
			],
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


# --- FEAT-094 (A-138): bộ tiêu chí cơ cấu, trình độ nhân sự KSNK ---------------------------------------------------


def approved_profile(**overrides):
	"""Bản bộ tiêu chí TT 16/2018 (nội dung của fixture khởi tạo) đã được duyệt; `overrides` ghi đè trường cha."""
	from tracecore.infection_program import structure_profile, structure_seed

	values = structure_seed.default_profile()
	values.update(overrides)
	values.setdefault("effective_from", add_days(today(), -1))
	doc = frappe.get_doc(values).insert(ignore_permissions=True)
	return structure_profile.approve(doc.name)


def qualify(employee_name, level="Bachelor", health=1):
	frappe.db.set_value("Employee", employee_name, {"tc_education_level": level, "tc_health_field": health})
	return employee_name


def certified(employee_name, certificate_type="Chứng chỉ KSNK"):
	"""Nhân viên có Certificate KSNK được công nhận còn hiệu lực."""
	from tracecore.infection_program.tests import training_fixtures as tfx

	current = frappe.db.get_single_value(SETTINGS, "ic_certificate_types") or ""
	if certificate_type not in current.splitlines():
		tfx.accept_certificates(*[line for line in current.splitlines() if line], certificate_type)
	tfx.certificate(employee_name, certificate_type)
	return employee_name


def qualified_employee(first_name, level="Bachelor"):
	"""Nhân viên đạt đủ trình độ, khối ngành sức khỏe và chứng chỉ KSNK."""
	return certified(qualify(employee(first_name), level=level))
