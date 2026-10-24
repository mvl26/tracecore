"""Minimal authenticated bootstrap for the independent TraceCore Home."""

import frappe
from frappe.sessions import get_csrf_token

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.flags.redirect_location = "/login?redirect-to=/tracecore"
		raise frappe.Redirect(http_status_code=302)

	context.update({"lang": frappe.local.lang, "csrf_token": get_csrf_token()})
