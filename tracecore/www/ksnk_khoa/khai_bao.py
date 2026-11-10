"""Cổng khoa — khai báo bệnh truyền nhiễm của khoa (SCR-61 DEPT, FEAT-069, UC-53 bước 5-6; FR-M14-10, .1; BRU-MDR-005;
A-150 Q4).

Trang Portal cần đăng nhập; R08/R12 chỉ khoa có User Permission Department. Người dùng có màn SCR-61 trên Desk (R01,
R11, R13) được chuyển sang `/app/tc-ksnk/o-dich`. Chữ hiển thị dịch ở server (``_()``) rồi đưa xuống JS; ghi qua
``tracecore.v1.outbreak.create_report`` / ``record_reported`` (``@idempotent``). Mã người bệnh chỉ hiện dạng che.
"""

from urllib.parse import quote

import frappe
from frappe import _

from tracecore.microbiology import notifiable
from tracecore.ui import ksnk
from tracecore.v1 import outbreak as api

no_cache = 1
ROUTE = "/ksnk-khoa/khai-bao"


def labels():
	return {
		"title": _("Notifiable communicable diseases"),
		"department": _("Department"),
		"patient_code": _("Patient Code"),
		"code_hint": _("The patient code is encrypted and shown masked. Do not enter the patient name."),
		"disease": _("Disease"),
		"group": _("Group"),
		"diagnosed_on": _("Diagnosed On"),
		"due_by": _("Due By"),
		"status": _("Status"),
		"code": _("Code"),
		"create": _("Record notifiable case"),
		"creating": _("Saving..."),
		"created": _("Report {0} recorded"),
		"created_reason": _(
			"Report on the national surveillance system before the due time, then record the date and reference here."
		),
		"choose": _("— Choose —"),
		"required": _("Required"),
		"reported": _("Record as reported"),
		"reported_on": _("Reported On"),
		"report_ref": _("Report Reference"),
		"save": _("Save"),
		"cancel": _("Cancel"),
		"saved": _("Report {0} updated"),
		"no_reports": _("No notifiable disease report in this department."),
		"missing_groups": _("No reporting deadline is configured for disease group {0}."),
		"note": _(
			"The reporting deadline follows the configured disease group A/B/C (awaiting confirmation of the current regulation — OQ-V12-03). TraceCore only tracks whether the case was reported."
		),
		"states": {
			notifiable.STATE_WAITING: _("Awaiting report"),
			notifiable.STATE_OVERDUE: _("Overdue — not reported"),
			notifiable.STATE_MISSING_REF: _("Report reference missing"),
			notifiable.STATE_REPORTED: _("Reported"),
			notifiable.STATE_LATE: _("Reported late"),
			notifiable.STATE_NO_DEADLINE: _("No deadline configured"),
			notifiable.STATE_CANCELLED: _("Cancelled"),
		},
		"left": _("{0} h {1} min left"),
		"offline_title": _("No network connection"),
		"offline_reason": _(
			"The report cannot be saved now. Keep the form and save when the connection returns."
		),
		"server_error": _("Server error"),
		"server_error_reason": _("The server could not process the request."),
		"server_error_action": _("Retry, or tell the infection control supervisor."),
		"retry": _("Retry"),
		"no_department": _("No department is assigned to you. Ask R10 to set your department."),
	}


def _desk_user():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == api.SCREEN_SLUG)
	return bool(set(frappe.get_roles()) & set(screen["roles"]))


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={quote(ROUTE)}"
		raise frappe.Redirect
	if _desk_user():
		frappe.local.flags.redirect_location = notifiable.DESK_LINK
		raise frappe.Redirect
	context.no_breadcrumbs = 1
	context.show_sidebar = 0
	context.title = _("Notifiable communicable diseases")
	context.ksnk_nav = "khai-bao"
	data = api.portal_context()
	context.department_label = ", ".join(row["label"] for row in data["departments"]) or "-"
	context.boot = {"data": data, "labels": labels()}
	return context
