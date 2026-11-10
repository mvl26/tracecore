"""Dữ liệu test FEAT-064: nhóm phẫu thuật, ca phẫu thuật giám sát NKVM (A-147)."""

import frappe
from frappe.utils import getdate

GROUP = "Surgical Procedure Group"
SSI = "Surgical Surveillance"
SETTINGS = "IC Program Settings"


def make_group(
	code="T-HPRO",
	name="Thay khớp háng test",
	t=120,
	implant=0,
	days=None,
	followups=((7, "Phone"),),
	monitored=1,
):
	if frappe.db.exists(GROUP, code):
		frappe.delete_doc(GROUP, code, force=True, ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": GROUP,
			"group_code": code,
			"group_name": name,
			"t_time_minutes": t,
			"has_implant": implant,
			"followup_days": str(days or (90 if implant else 30)),
			"is_monitored": monitored,
			"followups": [{"day_offset": d, "method": m} for d, m in followups],
		}
	)
	return doc.insert(ignore_permissions=True)


def ssi_values(department, group, surgery="2026-10-28", code="BN-0000006612", **extra):
	values = {
		"department": department,
		"procedure_group": group,
		"patient_code": code,
		"birth_year": 1961,
		"sex": "Female",
		"surgery_date": getdate(surgery),
		"asa_score": 3,
		"wound_class": "Clean",
		"duration_min": 150,
		"prophylaxis_given": 1,
		"prophylaxis_agent": "Cefazolin 2 g",
		"prophylaxis_minutes_before_incision": 45,
	}
	values.update(extra)
	return values


def make_ssi(department, group, **values):
	doc = frappe.get_doc({"doctype": SSI, **ssi_values(department, group, **values)})
	return doc.insert(ignore_permissions=True)


def set_threshold(minutes):
	frappe.db.set_single_value(SETTINGS, "prophylaxis_max_minutes", minutes)
