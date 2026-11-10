"""Cổng khoa — lệnh cách ly của khoa (SCR-60 DEPT, FEAT-068, UC-52; FR-M14-06, .1; BRU-MDR-003; A-146 Q4).

Trang Portal cần đăng nhập; R08/R12 chỉ khoa có User Permission Department. Link thông báo đa kháng
(``?isolate=<chủng>``) mở trang này với form điền sẵn; người dùng có màn SCR-60 trên Desk (R01, R11, R13) được chuyển
sang `/app/tc-ksnk/cach-ly`. Chữ hiển thị dịch ở server (``_()``) rồi đưa xuống JS; ghi qua
``tracecore.v1.isolation.create_order`` / ``close_order`` (``@idempotent``). Mã người bệnh chỉ hiện dạng che.
"""

from urllib.parse import quote

import frappe
from frappe import _

from tracecore.microbiology import isolation
from tracecore.ui import ksnk
from tracecore.v1 import isolation as api

no_cache = 1
ROUTE = "/ksnk-khoa/cach-ly"


def labels():
	return {
		"title": _("Isolation Orders"),
		"department": _("Department"),
		"create": _("Create isolation order"),
		"creating": _("Saving..."),
		"patient_code": _("Patient Code"),
		"patient_from_isolate": _("Patient (from multidrug-resistant isolate)"),
		"code_hint": _("The patient code is encrypted and shown masked. Do not enter the patient name."),
		"precaution": _("Precaution Type"),
		"reason": _("Reason"),
		"reason_detail": _("Reason Details"),
		"room": _("Isolation Room"),
		"no_room": _("No room — bedside isolation"),
		"room_free": _("{0} free"),
		"room_full": _("full"),
		"start_at": _("Start At"),
		"choose": _("— Choose —"),
		"required": _("Required"),
		"created": _("Isolation order {0} created"),
		"created_reason": _("The order is in the list of patients in isolation of the department."),
		"open_title": _("In isolation"),
		"open_count": _("{0} patients"),
		"order": _("Isolation order no."),
		"precaution_short": _("Precaution"),
		"room_short": _("Room"),
		"from": _("From"),
		"days": _("Days"),
		"bedside": _("Bedside"),
		"mdro": _("MDRO"),
		"end": _("End isolation"),
		"end_reason": _("End Reason"),
		"end_confirm": _("End this isolation"),
		"end_hint": _(
			"Enter why the isolation ends (for example: negative cultures, discharged, transferred)."
		),
		"ic_closes": _("Infection control closes this order"),
		"closed": _("Isolation order {0} ended"),
		"cancel": _("Cancel"),
		"no_orders": _("No patient in isolation in this department."),
		"rooms_title": _("Isolation rooms of the department"),
		"meets": _("Meets standard"),
		"not_met": _("Not met"),
		"not_checked": _("Not checked"),
		"in_use": _("In use ({0}/{1})"),
		"free": _("Room free"),
		"no_rooms": _("This department has no isolation room yet."),
		"offline_title": _("No network connection"),
		"offline_reason": _(
			"The order cannot be saved now. Keep the form and save when the connection returns."
		),
		"server_error": _("Server error"),
		"server_error_reason": _("The server could not process the request."),
		"server_error_action": _("Retry, or tell the infection control supervisor."),
		"retry": _("Retry"),
		"no_department": _("No department is assigned to you. Ask R10 to set your department."),
		"precautions": {value: _(value) for value in isolation.PRECAUTIONS},
		"reasons": {value: _(value) for value in isolation.REASONS},
	}


def _desk_user():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == api.SCREEN_SLUG)
	return bool(set(frappe.get_roles()) & set(screen["roles"]))


def get_context(context):
	isolate = frappe.form_dict.get("isolate") or ""
	if frappe.session.user == "Guest":
		target = ROUTE + (f"?isolate={quote(isolate)}" if isolate else "")
		frappe.local.flags.redirect_location = f"/login?redirect-to={quote(target)}"
		raise frappe.Redirect
	if _desk_user():
		frappe.local.flags.redirect_location = isolation.DESK_LINK + (
			f"?isolate={quote(isolate)}" if isolate else ""
		)
		raise frappe.Redirect
	context.no_breadcrumbs = 1
	context.show_sidebar = 0
	context.title = _("Isolation Orders")
	context.ksnk_nav = "cach-ly"
	data = api.portal_context(isolate=isolate or None)
	context.department_label = ", ".join(row["label"] for row in data["departments"]) or "-"
	context.boot = {"data": data, "labels": labels(), "isolate": isolate if data.get("prefill") else ""}
	return context
