"""Dữ liệu test M17 (FEAT-073): người chế biến, sự cố ngộ độc, buổi truyền thông, đơn vị suất ăn, tài liệu truyền thông."""

import frappe
from frappe.utils import add_days, today

from tracecore.tests import factories

R01, R02, R08, R11, R12, R13 = "TC R01", "TC R02", "TC R08", "TC R11", "TC R12", "TC R13"
SETTINGS = "IC Program Settings"


def make_department(name="ATTP Khoa Dinh dưỡng"):
	return factories.make_department(name)


def make_caterer(name="ATTP Công ty suất ăn D"):
	supplier = factories.make_supplier(name)
	frappe.db.set_value("Supplier", supplier, "tc_ic_service_type", "Catering")
	return supplier


def make_check(full_name="Nhân viên bếp 1", checked_on=None, next_due=None, fit="Fit", submit=True, **values):
	checked_on = checked_on or add_days(today(), -30)
	doc = frappe.get_doc(
		{
			"doctype": "Food Handler Health Check",
			"full_name": full_name,
			"checked_on": checked_on,
			"next_due": next_due or add_days(today(), 300),
			"fit_for_work": fit,
			**values,
		}
	)
	if not doc.employee and not doc.supplier:
		doc.supplier = make_caterer()
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def set_threshold(value):
	frappe.db.set_single_value(SETTINGS, "foodborne_outbreak_threshold", value)


def make_event(affected=4, department=None, submit=True, **values):
	doc = frappe.get_doc(
		{
			"doctype": "Foodborne Event",
			"event_date": values.pop("event_date", today()),
			"location": values.pop("location", "Căng tin"),
			"department": department or make_department(),
			"affected_count": affected,
			"suspected_food": values.pop("suspected_food", "Cơm gà"),
			**values,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def make_session(department=None, audience="Patient Families", attendees=26, **values):
	return frappe.get_doc(
		{
			"doctype": "IC Education Session",
			"session_date": values.pop("session_date", today()),
			"department": department or make_department(),
			"audience": audience,
			"topic": values.pop("topic", "Hand Hygiene"),
			"title": values.pop("title", "Vệ sinh tay khi chăm trẻ"),
			"attendee_count": attendees,
			**values,
		}
	).insert(ignore_permissions=True)


def make_material(
	code="TL-VST-01", version=1, status="Effective", doc_type="Communication Material", **values
):
	doc = frappe.get_doc(
		{
			"doctype": "IC Procedure Document",
			"doc_code": code,
			"title": values.pop("title", "Vệ sinh tay đúng cách cho người nhà"),
			"doc_type": doc_type,
			"version_no": version,
			"measure_group": "Patient Counselling",
			"issued_on": values.pop("issued_on", today()),
			"status": status,
			**values,
		}
	)
	return doc.insert(ignore_permissions=True)


def attach(doc, content=b"tai lieu", file_name="tai-lieu.txt"):
	file_url = factories.attach_private_file(content, file_name)
	frappe.db.set_value(doc.doctype, doc.name, "file", file_url)
	return file_url


def make_dept_user(email, role, department):
	user = factories.make_user(email, [role])
	if not frappe.db.exists(
		"User Permission", {"user": user, "allow": "Department", "for_value": department}
	):
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Department", "for_value": department}
		).insert(ignore_permissions=True)
	return user


make_user = factories.make_user
