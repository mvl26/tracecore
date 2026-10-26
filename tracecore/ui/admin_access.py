"""Optional rollout guard for Desk; does not affect APIs or kiosk authentication."""

import frappe


def is_desk_path(path):
	path = path.rstrip("/")
	return (path == "/app" or path.startswith("/app/")) and path != "/app/station"


def before_request():
	if not frappe.conf.get("tracecore_admin_rollout"):
		return
	request = getattr(frappe.local, "request", None)
	if not request or not is_desk_path(request.path):
		return
	if frappe.session.user == "Administrator":
		return
	if frappe.session.user != "Guest" and frappe.db.exists(
		"Has Role", {"parent": frappe.session.user, "parenttype": "User", "role": "TraceCore Desk Access"}
	):
		return
	frappe.local.flags.redirect_location = "/tracecore"
	raise frappe.Redirect
