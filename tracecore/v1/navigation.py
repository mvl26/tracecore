"""Read-only navigation. Destination permissions and card authentication remain authoritative."""

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
}
IMPLEMENTED_STEPS = {"T2", "T4", "T6"}
MANAGEMENT_TARGETS = (
	"Instrument",
	"Instrument Set Type",
	"Set Unit",
	"Pack",
	"Wash Batch",
	"Sterile Putaway",
	"Sterile Location",
	"Equipment",
	"Process Program",
	"Par Level",
	"Employee",
	"Station Competency",
	"Item",
	"Batch",
	"Stock Entry",
	"Zone Station",
	"Printer",
	"Label Template",
	"Print Job",
	"Audit Log",
)


@frappe.whitelist(methods=["GET"])
def context():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to open TraceCore."), frappe.PermissionError)
	roles = set(frappe.get_roles())
	admin = frappe.session.user == "Administrator" or "System Manager" in roles
	manager = admin or bool(roles & {"TC R01", "TC R02", "TC R09", "TC R10"})
	allowed = (
		set(STEP_ROLES)
		if admin or roles & {"TC R01", "TC R02", "TC R10"}
		else {step for step, required in STEP_ROLES.items() if roles & required}
	)
	stations = []
	if allowed:
		for row in frappe.get_list(
			"Zone Station",
			filters={"is_zone": 0, "is_active": 1},
			fields=["name", "zone_station_name", "station_step"],
			order_by="station_step asc, name asc",
			limit_page_length=0,
		):
			if row.station_step in allowed:
				stations.append(
					{
						"name": row.name,
						"label": row.zone_station_name,
						"step": row.station_step,
						"implemented": row.station_step in IMPLEMENTED_STEPS,
					}
				)
	return {
		"stations": stations,
		"management": [
			{"doctype": dt, "route": "/app/" + frappe.scrub(dt).replace("_", "-")}
			for dt in MANAGEMENT_TARGETS
			if manager and frappe.has_permission(dt, ptype="read")
		],
		"department": admin or "TC R08" in roles,
	}
