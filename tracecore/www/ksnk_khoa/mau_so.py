"""Cổng khoa — mẫu số ngày & đợt thiết bị (SCR-55 DEPT, FEAT-062, UC-47; FR-M13-02, FR-M13-04, FR-M12-07; A-141 Q4).

Trang Portal cần đăng nhập; R08/R12 chỉ khoa có User Permission Department, R01/R11 chọn mọi khoa nội trú. Mọi chữ hiển
thị dịch ở server (``_()``) rồi đưa xuống JS; ghi qua ``tracecore.v1.hai.census_upsert_portal`` và
``device_episode_portal`` (``@idempotent``). Mã người bệnh chỉ hiện dạng che; phiếu gói dự phòng chấm trên PDA (Page
`station`), trang này chỉ hiện kết quả gói hôm nay của từng đợt.
"""

import frappe
from frappe import _

from tracecore.v1 import hai as api

no_cache = 1
ROUTE = "/ksnk-khoa/mau-so"


def labels():
	return {
		"title": _("Daily Census and Device Episodes"),
		"department": _("Department"),
		"census_date": _("Census Date"),
		"census_title": _("Daily census {0}"),
		"patient_count": _("Inpatients"),
		"vent_count": _("On Ventilator"),
		"cvc_count": _("Central Line"),
		"urinary_catheter_count": _("Urinary Catheter"),
		"admissions": _("Admissions"),
		"save": _("Save census"),
		"save_changes": _("Save changes"),
		"saving": _("Saving..."),
		"copy": _("Copy from the previous day"),
		"saved": _("Census saved"),
		"saved_reason": _("Daily census of {0} is saved."),
		"existing": _("Census {0} already entered ({1})."),
		"locked": _("Period locked"),
		"missing_title": _("No census for {0} yet"),
		"missing_reason": _(
			"Enter the counts of that day below. Inpatient wards are reminded at the configured time."
		),
		"count_invalid": _("Count not valid"),
		"count_invalid_reason": _("{0} must be a whole number of 0 or more."),
		"count_action": _("Correct the {0} box and save again."),
		"not_saved": _("Census not saved"),
		"too_many": _("Patients with {0} ({1}) cannot be more than inpatients ({2})."),
		"episodes": _("Open device episodes"),
		"code": _("Patient Code"),
		"device": _("Device"),
		"inserted_on": _("Inserted On"),
		"removed_on": _("Removed On"),
		"days": _("Days"),
		"bundle_today": _("Bundle today"),
		"no_episode": _("No open device episode."),
		"open_episode": _("Open device episode"),
		"close_episode": _("Close episode"),
		"cancel": _("Cancel"),
		"birth_year": _("Birth Year"),
		"sex": _("Sex"),
		"code_hint": _("The patient code is encrypted and shown masked. Do not enter the patient name."),
		"episode_required": _("Device and patient code required"),
		"episode_required_reason": _("An episode needs the device and the patient code."),
		"episode_required_action": _("Choose the device and enter the patient code, then save."),
		"episode_opened": _("Episode opened"),
		"episode_closed": _("Episode closed"),
		"episode_updated": _("The device episode list is updated."),
		"bundle_hint": _("Prevention bundle audits are posted on the department PDA (audit screen)."),
		"recent": _("Last 7 days"),
		"date": _("Date"),
		"source": _("Source"),
		"no_recent": _("No census in the last 7 days."),
		"offline_title": _("No network connection"),
		"offline_reason": _(
			"The census cannot be saved now. Keep the numbers and save when the connection returns."
		),
		"server_error": _("Server error"),
		"server_error_reason": _("The server could not process the request."),
		"server_error_action": _("Retry, or tell the infection control supervisor."),
		"retry": _("Retry"),
		"no_department": _("No inpatient department is assigned to you. Ask R10 to set your department."),
		"device_source": _("Device days for rates come from: {0}"),
		"pass": _("Pass"),
		"fail": _("Fail"),
		"not_checked": _("Not checked"),
		"devices": {value: _(value) for value in ("Ventilator", "Central Line", "Urinary Catheter")},
		"sexes": {value: _(value) for value in ("Male", "Female", "Other")},
		"sources": {value: _(value) for value in ("Manual", "Import", "Daily Census", "Device Episode")},
	}


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={ROUTE}"
		raise frappe.Redirect
	context.no_breadcrumbs = 1
	context.show_sidebar = 0
	context.title = _("Daily Census and Device Episodes")
	context.ksnk_nav = "mau-so"
	data = api.portal_context(
		department=frappe.form_dict.get("department"), census_date=frappe.form_dict.get("date")
	)
	departments = {row["name"]: row["label"] for row in data["departments"]}
	context.department_label = departments.get(data.get("department")) or "-"
	context.boot = {"data": data, "labels": labels(), "user": frappe.session.user}
	return context
