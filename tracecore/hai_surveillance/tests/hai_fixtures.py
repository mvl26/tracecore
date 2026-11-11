"""Dữ liệu test FEAT-063: định nghĩa ca, ca NKBV, kỳ báo cáo (A-144)."""

import frappe
from frappe.utils import add_days, getdate

from tracecore.hai_surveillance.tests import factories as f

R01, R08, R10, R11, R12, R13 = f.R01, f.R08, f.R10, f.R11, f.R12, f.R13


def make_definition(
	code="TVAP",
	device="Ventilator",
	hours=48,
	days=2,
	effective_from="2026-01-01",
	approve=True,
	site="Ventilator-associated Pneumonia",
):
	"""Phiên bản định nghĩa ca kế tiếp của ``code`` (đã duyệt nếu ``approve``)."""
	draft = frappe.db.get_value("HAI Case Definition", {"def_code": code, "docstatus": 0}, "name")
	if draft:
		frappe.delete_doc("HAI Case Definition", draft, force=True, ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "HAI Case Definition",
			"def_code": code,
			"title": f"{code} test",
			"infection_site": site,
			"device_type": device,
			"min_hours_after_admission": hours,
			"min_device_days_before_onset": days,
			"effective_from": getdate(effective_from),
			"legal_ref": "QĐ 3916/QĐ-BYT",
			"criteria": [{"criterion": "Tiêu chí test"}],
		}
	).insert(ignore_permissions=True)
	if approve:
		doc.submit()
	return doc


def clear_definitions(code):
	for name in frappe.get_all("HAI Case Definition", filters={"def_code": code}, pluck="name"):
		frappe.db.delete("HAI Case Definition Criterion", {"parent": name})
		frappe.db.delete("HAI Case Definition", {"name": name})


def case_values(
	department, onset="2026-10-20", admitted="2026-10-14 08:00:00", code="BN-0000004821", **extra
):
	return {
		"department": department,
		"patient_code": code,
		"birth_year": 1958,
		"sex": "Male",
		"admission_at": admitted,
		"onset_date": getdate(onset),
		"def_code": extra.pop("def_code", "TVAP"),
		**extra,
	}


def make_case(department, **values):
	doc = frappe.get_doc({"doctype": "HAI Case", **case_values(department, **values)})
	return doc.insert(ignore_permissions=True)


def make_episode(department, inserted_on, code="BN-0000004821", device="Ventilator", removed_on=None):
	return f.make_episode(
		department, code=code, device=device, inserted_on=inserted_on, removed_on=removed_on
	)


def make_isolate(department, patient="BN-0000004821", lab="L-063-1", collected_on="2026-10-21", flags=None):
	"""Chủng vi sinh tạo thẳng (cờ dịch vụ M14), không import module M14."""
	doc = frappe.get_doc(
		{
			"doctype": "Microbiology Isolate",
			"lab_sample_id": lab,
			"organism": "kpn",
			"patient_code": patient,
			"birth_year": 1958,
			"sex": "Male",
			"department": department,
			"specimen_type": "Blood",
			"collected_on": getdate(collected_on),
			"source": "Import",
			"susceptibility": [{"antibiotic": "MEM", "result": "R"}],
		}
	)
	doc.flags.tc_micro = True
	doc.insert(ignore_permissions=True)
	if flags:
		frappe.db.set_value("Microbiology Isolate", doc.name, {"is_mdro": 1, "mdro_flags": flags})
		doc.reload()
	return doc


def month_days(month):
	start = getdate(f"{month}-01")
	day = start
	while day.month == start.month:
		yield day
		day = add_days(day, 1)
