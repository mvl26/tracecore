"""Dữ liệu test M13 mẫu số ngày, đợt thiết bị (FEAT-062)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.tests import factories

R01, R08, R10, R11, R12, R13 = "TC R01", "TC R08", "TC R10", "TC R11", "TC R12", "TC R13"


def make_ward(name="KSNK Test ICU", inpatient=1, source="Daily Census"):
	"""Khoa nội trú (cờ `tc_inpatient`) với nguồn ngày thiết bị."""
	department = factories.make_department(name)
	frappe.db.set_value(
		"Department", department, {"tc_inpatient": inpatient, "tc_device_day_source": source, "disabled": 0}
	)
	return department


def census_values(department, census_date=None, patients=18, vent=9, cvc=11, urinary=12, admissions=3):
	return {
		"department": department,
		"census_date": getdate(census_date or add_days(today(), -1)),
		"patient_count": patients,
		"vent_count": vent,
		"cvc_count": cvc,
		"urinary_catheter_count": urinary,
		"admissions": admissions,
	}


def make_census(department, census_date=None, source="Manual", **counts):
	doc = frappe.get_doc({"doctype": "Ward Daily Census", "source": source, **census_values(department, census_date, **counts)})
	return doc.insert(ignore_permissions=True)


def make_episode(department, code="BN-0000004821", device="Ventilator", inserted_on=None, **values):
	doc = frappe.get_doc(
		{
			"doctype": "Device Episode",
			"department": department,
			"device_type": device,
			"patient_code": code,
			"birth_year": 1960,
			"sex": "Male",
			"inserted_on": getdate(inserted_on or add_days(today(), -4)),
			**values,
		}
	)
	return doc.insert(ignore_permissions=True)


BUNDLE_BY_DEVICE = {"Ventilator": "VAP", "Central Line": "CLABSI", "Urinary Catheter": "CAUTI"}


def bundle_template(bundle="VAP"):
	"""Mẫu gói dự phòng đã duyệt (Tất cả-hoặc-không, 2 mục) — tạo bằng `frappe.get_doc`, không import M12."""
	code = f"T-{bundle}-062"
	name = frappe.db.get_value("Audit Template", {"template_code": code, "docstatus": 1}, "name")
	if name:
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Audit Template",
			"template_code": code,
			"title": f"{bundle} bundle",
			"audit_type": "Prevention Bundle",
			"bundle_type": bundle,
			"scoring_method": "All or None",
			"effective_from": today(),
			"items": [
				{"item_code": f"{bundle}-0{i}", "section": bundle, "question": f"Item {i}", "answer_type": "Pass/Fail", "weight": 1}
				for i in (1, 2)
			],
		}
	).insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def observer():
	name = frappe.db.get_value("Employee", {"first_name": "Bundle 062 Observer"}, "name")
	return name or factories.make_employee(first_name="Bundle 062 Observer").name


def post_bundle(episode, result="Pass"):
	"""Phiếu gói dự phòng đã ghi sổ cho đợt (hôm nay)."""
	template = bundle_template(BUNDLE_BY_DEVICE[episode.device_type])
	items = frappe.get_all("Audit Template Item", filters={"parent": template}, pluck="item_code", order_by="idx")
	doc = frappe.get_doc(
		{
			"doctype": "Audit Session",
			"audit_template": template,
			"department": episode.department,
			"observer": observer(),
			"device_episode": episode.name,
			"answers": [
				{"item_code": code, "answer": "Fail" if result == "Fail" and i == 0 else "Pass", "note": "x"}
				for i, code in enumerate(items)
			],
		}
	).insert(ignore_permissions=True)
	doc.submit()
	return doc


def make_dept_user(email, role, department):
	"""Người dùng có role và User Permission Department (R08/R12 của khoa)."""
	user = factories.make_user(email, [role])
	if not frappe.db.exists("User Permission", {"user": user, "allow": "Department", "for_value": department}):
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Department", "for_value": department}
		).insert(ignore_permissions=True)
	return user
