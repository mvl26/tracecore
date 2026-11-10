"""Dữ liệu test FEAT-069 (A-150): danh mục bệnh, giờ khai báo, ngưỡng cụm ca, ca NKBV/chủng tạo thẳng."""

import frappe
from frappe.utils import getdate

from tracecore.core import patient_code
from tracecore.microbiology.tests import factories as mf
from tracecore.microbiology.tests.test_isolation import make_clinical, make_dept_user

SETTINGS = "IC Program Settings"


def make_disease(code="T-DENGUE", name="Sốt xuất huyết Dengue", group="B", disabled=0):
	if frappe.db.exists("Communicable Disease", code):
		frappe.db.set_value(
			"Communicable Disease",
			code,
			{"disease_name": name, "disease_group": group, "disabled": disabled},
		)
		return code
	return (
		frappe.get_doc(
			{
				"doctype": "Communicable Disease",
				"disease_code": code,
				"disease_name": name,
				"disease_group": group,
				"disabled": disabled,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def set_hours(a=None, b=None, c=None):
	for group, value in (("a", a), ("b", b), ("c", c)):
		frappe.db.set_single_value(SETTINGS, f"notifiable_hours_{group}", value)


def make_rule(title="T cụm", source="HAI Case", window_days=14, min_cases=3, **values):
	return frappe.get_doc(
		{
			"doctype": "Cluster Alert Rule",
			"title": title,
			"source": source,
			"window_days": window_days,
			"min_cases": min_cases,
			**values,
		}
	).insert(ignore_permissions=True)


def make_case(department, onset, code, site="Ventilator-associated Pneumonia", status="Confirmed"):
	"""Ca NKBV tạo thẳng bằng SQL-level insert (không import M13): Xác định = ghi sổ, Nghi ngờ = Nháp."""
	doc = frappe.get_doc(
		{
			"doctype": "HAI Case",
			"department": department,
			"patient_code": code,
			"birth_year": 1958,
			"sex": "Male",
			"admission_at": "2026-09-01 08:00:00",
			"onset_date": getdate(onset),
			"infection_site": site,
		}
	)
	doc.flags.tc_system = True
	doc.flags.ignore_validate = True
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	values = {
		"infection_site": site,
		"status": status,
		"onset_date": getdate(onset),
		"patient_code_masked": patient_code.mask(code),
		"patient_code_hash": patient_code.hash_of(code),
	}
	if status != "Suspected":
		values["docstatus"] = 1
	frappe.db.set_value("HAI Case", doc.name, values, update_modified=False)
	return doc.name


def make_isolate(department, lab, patient, collected_on, organism="kpn", mdro=0, flags=None):
	mf.make_organism()
	doc = mf.new_isolate(
		lab=lab, patient=patient, collected_on=collected_on, department=department, organism=organism
	)
	frappe.db.set_value(
		"Microbiology Isolate", doc.name, {"is_mdro": mdro, "mdro_flags": flags or ""}, update_modified=False
	)
	return doc.name
