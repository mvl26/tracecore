"""Read-only context for the clean-zone workspace. Lifecycle writes stay in station RPCs."""

import frappe
from frappe import _
from frappe.utils import today

from tracecore.v1.admin_ui import available_roles


def require_workspace(role="R04", step="T3"):
	if role != "R04" or role not in available_roles() or step not in ("T3", "T4"):
		frappe.throw(_("You cannot open this station."), frappe.PermissionError)


def queue_candidates(units, gates, step):
	previous = "T2" if step == "T3" else "T3"
	passed = {(g.set_unit, int(g.cycle_no or 0), g.step) for g in gates if g.result == "Pass"}
	return [
		u
		for u in units
		if u.status == "Processing"
		and not u.active_cycle_id
		and (u.name, int(u.current_cycle_no or 0), previous) in passed
		and (u.name, int(u.current_cycle_no or 0), step) not in passed
	]


@frappe.whitelist(methods=["GET"])
def personal_requests():
	require_workspace()
	if not frappe.db.exists("DocType", "Par Override"):
		return {"available": False, "rows": []}
	if not frappe.has_permission("Par Override", ptype="read"):
		frappe.throw(_("You cannot read the requests."), frappe.PermissionError)
	return {
		"available": True,
		"rows": frappe.get_list(
			"Par Override",
			filters={"owner": frappe.session.user},
			fields=["name", "set_unit", "status", "reason", "requested_at", "extra_cycles", "valid_until"],
			order_by="modified desc",
			limit_page_length=100,
		),
	}


@frappe.whitelist(methods=["GET"])
def history():
	require_workspace()
	rows = []
	for doctype in ("Assembly Record", "Pack"):
		if not frappe.has_permission(doctype, ptype="read"):
			continue
		rows.extend(
			frappe.get_list(
				doctype,
				filters={"owner": frappe.session.user},
				fields=["name", "set_unit", "docstatus", "modified"],
				order_by="modified desc",
				limit_page_length=100,
			)
		)
	return sorted(rows, key=lambda row: str(row.modified), reverse=True)


@frappe.whitelist(methods=["GET"])
def workspace(step="T3"):
	require_workspace(step=step)
	units = frappe.get_list(
		"Set Unit",
		filters={"status": ["in", ["Processing", "Reprocess"]]},
		fields=["name", "set_type", "status", "current_cycle_no", "active_cycle_id"],
		order_by="modified desc",
		limit_page_length=1001,
	)
	gates = (
		# Gate rows are internal derived state: bound strictly to permission-filtered parent units above.
		frappe.get_all(
			"Step Gate Result",
			filters={"set_unit": ["in", [u.name for u in units]]},
			fields=["set_unit", "cycle_no", "step", "result"],
			limit_page_length=20000,
		)
		if units
		else []
	)
	queue = queue_candidates(units, gates, step)
	# Deliberately expose only public station identity; never network/peripheral configuration.
	stations = frappe.get_all(
		"Zone Station",
		filters={"station_step": step, "is_active": 1},
		fields=["name", "zone_station_name"],
		order_by="name",
		limit_page_length=100,
	)
	return {
		"queue": queue[:100],
		"waiting": len(queue),
		"capped": len(units) > 1000,
		"issues": [u for u in units if u.status == "Reprocess"][:100],
		"stations": stations,
		"card_ready": frappe.db.has_column("Employee", "tc_card_id"),
		"assembly_ready": frappe.get_meta("Assembly Record").has_field("lines"),
		"completed": len(
			frappe.get_list(
				"Assembly Record" if step == "T3" else "Pack",
				filters={"owner": frappe.session.user, "docstatus": 1, "modified": [">=", today()]},
				fields=["name"],
				limit_page_length=1001,
			)
		),
	}


@frappe.whitelist(methods=["GET"])
def context(set_id, step="T3"):
	require_workspace(step=step)
	from tracecore.core.gs1 import parse_scan

	raw = str(set_id).strip()
	scanned = parse_scan(raw)
	name = scanned["id"] if scanned["type"] == "set" else raw
	rows = frappe.get_list(
		"Set Unit",
		filters={"name": name},
		fields=[
			"name",
			"set_type",
			"status",
			"current_cycle_no",
			"active_cycle_id",
			"cycle_bom_version",
			"cycles_used",
			"max_cycles",
		],
		limit_page_length=1,
	)
	if not rows:
		frappe.throw(_("Set not found, or you cannot view it."), frappe.PermissionError)
	unit = rows[0]
	from tracecore.v1.set_type import bom

	bill = bom(unit.set_type, unit.cycle_bom_version or None)
	# Internal gate state is exposed only after the parent passed the permission-filtered lookup.
	gates = frappe.get_all(
		"Step Gate Result",
		filters={"set_unit": unit.name, "cycle_no": unit.current_cycle_no},
		fields=["step", "result"],
		limit_page_length=20,
	)
	from tracecore.par import check as par_check

	# Older local installations may have only the T4 par stub. Never infer instrument limits in the UI.
	par = par_check.evaluate(dict(unit)) if hasattr(par_check, "evaluate") else {"state": "unavailable"}
	return {"set": unit, "bom": bill, "gates": gates, "par": par}
