"""Read-only navigation. Destination permissions and card authentication remain authoritative."""

from urllib.parse import quote

import frappe
from frappe import _

STEP_ROLES = {
	"T1": {"TC R03"},
	"T2": {"TC R03"},
	"T3": {"TC R04"},
	"T4": {"TC R04"},
	"T5": {"TC R05"},
	"T5b": {"TC R02", "TC R05"},
	"T6": {"TC R06"},
	"T7": {"TC R07"},
	"T8": {"TC R08"},
}
# T5b là chế độ "Dỡ mẻ" của màn T5 trên kiosk
IMPLEMENTED_STEPS = {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"}
MANAGEMENT_TARGETS = ("Instrument", "Instrument Set Type", "Set Unit", "Pack", "Equipment", "Par Level")


def _is_admin(roles):
	return frappe.session.user == "Administrator" or "System Manager" in roles


def _allowed_steps(roles):
	if _is_admin(roles) or roles & {"TC R01", "TC R02", "TC R10"}:
		return set(STEP_ROLES)
	return {step for step, required in STEP_ROLES.items() if roles & required}


def _stations(allowed, step=None):
	if not allowed or (step and step not in allowed):
		return []
	filters = {"is_zone": 0, "is_active": 1}
	if step:
		filters["station_step"] = step
	return [
		row
		for row in frappe.get_list(
			"Zone Station",
			filters=filters,
			fields=["name", "zone_station_name", "station_step"],
			order_by="station_step asc, name asc",
			limit_page_length=0,
		)
		if row.station_step in allowed
	]


def station_links(step):
	"""Trạm kiosk của một bước mà người dùng được mở; đăng nhập thẻ + PIN tại trạm vẫn là cổng thật."""
	if step not in IMPLEMENTED_STEPS:
		return []
	return [
		{
			"name": row.name,
			"label": row.zone_station_name,
			"step": row.station_step,
			"url": "/app/station?station=" + quote(row.name, safe=""),
		}
		for row in _stations(_allowed_steps(set(frappe.get_roles())), step)
	]


@frappe.whitelist(methods=["GET"])
def context():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to open TraceCore."), frappe.PermissionError)
	roles = set(frappe.get_roles())
	admin = _is_admin(roles)
	manager = admin or bool(roles & {"TC R01", "TC R02", "TC R09", "TC R10"})
	stations = [
		{
			"name": row.name,
			"label": row.zone_station_name,
			"step": row.station_step,
			"implemented": row.station_step in IMPLEMENTED_STEPS,
		}
		for row in _stations(_allowed_steps(roles))
	]
	return {
		"stations": stations,
		"management": [
			{"doctype": dt, "route": "/app/" + frappe.scrub(dt).replace("_", "-")}
			for dt in MANAGEMENT_TARGETS
			if manager and frappe.has_permission(dt, ptype="read")
		],
		"department": admin or "TC R08" in roles,
	}
