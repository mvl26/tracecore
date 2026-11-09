"""Cổng khoa — báo phơi nhiễm nghề nghiệp (SCR-63 DEPT, FEAT-071, UC-55, FR-M16-01, A-137 Q4).

Trang Portal độc lập (FEAT-062 sau gắn vào menu "KSNK khoa"): cần đăng nhập; nhân viên báo cho mình, R08/R12 báo thay
nhân viên cùng khoa. Mọi chữ hiển thị dịch ở server (``_()``) rồi đưa xuống JS; ghi qua RPC
``tracecore.v1.exposure.report_portal`` (``@idempotent``). Danh sách "Hồ sơ của tôi" không có mã BN nguồn (UC-55 A4).
"""

import frappe
from frappe import _

from tracecore.v1 import exposure as api

no_cache = 1
ROUTE = "/ksnk-khoa/bao-phoi-nhiem"


def labels():
	return {
		"title": _("Exposure Report"),
		"department": _("Department"),
		"reporter": _("Reported for"),
		"myself": _("Myself"),
		"step1": _("Type and time"),
		"step2": _("Circumstances"),
		"step3": _("Confirm"),
		"step1_title": _("Step 1: type of exposure"),
		"step2_title": _("Step 2: what happened"),
		"step3_title": _("Step 3: check and send"),
		"when": _("When did it happen?"),
		"activity": _("What were you doing?"),
		"device": _("Device or object"),
		"source_question": _("Is the source patient known?"),
		"source_code": _("Source patient code (optional)"),
		"source_code_hint": _("The code is encrypted and shown masked; do not enter the patient name."),
		"continue": _("Continue"),
		"back": _("Back"),
		"send": _("Send report"),
		"sending": _("Sending..."),
		"retry": _("Retry"),
		"new_report": _("Report another exposure"),
		"notified": _("The head of infection control and the supervisor are notified at once."),
		"done_title": _("Exposure {0} reported"),
		"done_reason": _("The head of infection control and the supervisor have been notified."),
		"procedure": _("First-aid procedure"),
		"no_procedure": _(
			"Follow the first-aid steps of the hospital and call the infection control team now."
		),
		"open": _("Open"),
		"offline_title": _("No network connection"),
		"offline_reason": _("The report is kept in this browser and sent when the connection returns."),
		"queued_title": _("Report kept in this browser"),
		"queued_reason": _("It is sent when the connection returns. The patient code is not kept offline."),
		"queued_count": _("{0} report(s) waiting to be sent"),
		"type_required": _("Exposure type is required"),
		"type_required_reason": _("The report needs the type of exposure."),
		"type_required_action": _("Choose one of the types, then continue."),
		"future_title": _("Exposure time is in the future"),
		"future_reason": _("The exposure time is later than now."),
		"future_action": _("Check the date and time of the exposure, then continue."),
		"server_error": _("Server error"),
		"server_error_reason": _("The server could not process the request."),
		"server_error_action": _("Retry, or report the exposure to the infection control team by phone."),
		"my_records": _("My exposure records"),
		"no_records": _("You have no exposure records."),
		"followups": _("Follow-up steps"),
		"due": _("Due"),
		"done_on": _("Done on"),
		"not_yet": _("Not yet"),
		"no_employee": _(
			"Your account is not linked to a staff record. Ask the department nurse to report for you."
		),
		"exposure_type": _("Exposure Type"),
		"occurred_at": _("Occurred At"),
		"source_known": _("Source Known"),
		"code_entered": _("patient code entered"),
		"status": _("Status"),
		"failed_title": _("Some reports kept offline were not accepted"),
		"failed_action": _("Report these exposures again or call the infection control team."),
		"dismiss": _("Dismiss"),
		"types": {value: _(value, context="Occupational Exposure") for value in api.config.EXPOSURE_TYPES},
		"sources": {value: _(value, context="Occupational Exposure") for value in ("Yes", "No", "Unknown")},
		"statuses": {
			value: _(value, context="Occupational Exposure")
			for value in ("New", "Following Up", "Completed", "Cancelled")
		},
	}


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={ROUTE}"
		raise frappe.Redirect
	context.no_breadcrumbs = 1
	context.show_sidebar = 0
	context.title = _("Exposure Report")
	data = api.portal_context()
	context.department = data.get("department")
	# user: hàng đợi offline trong trình duyệt tách theo tài khoản (máy dùng chung của khoa)
	context.boot = {"data": data, "labels": labels(), "user": frappe.session.user}
	return context
