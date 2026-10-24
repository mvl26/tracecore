"""Authoritative, read-only context for the independent TraceCore Home."""

import hashlib
import json

import frappe
from frappe import _

from tracecore.v1 import navigation
from tracecore.v1._common import server_time

ROUTE_KEYS = frozenset({"station", "search", "set-units", "packs", "equipment", "par-levels", "frappe-admin"})


def _identity(user: str, roles: set[str]) -> dict:
	# Reuse the launcher query and step rules, including active stations and get_list permissions.
	stations = navigation.context()["stations"] if frappe.has_permission("Zone Station", ptype="read") else []
	return {
		"name": user,
		"full_name": frappe.get_cached_value("User", user, "full_name") or user,
		"roles": sorted(roles),
		"stations": [{**station, "label": _(station["label"])} for station in stations],
	}


def _doctype_targets() -> list[dict]:
	return [
		{
			"doctype": "Set Unit",
			"key": "set-units",
			"label": _("Instrument sets"),
			"description": _("Browse instrument sets you can read."),
		},
		{
			"doctype": "Pack",
			"key": "packs",
			"label": _("Packs"),
			"description": _("Browse packs you can read."),
		},
		{
			"doctype": "Equipment",
			"key": "equipment",
			"label": _("Equipment"),
			"description": _("Browse equipment you can read."),
		},
		{
			"doctype": "Par Level",
			"key": "par-levels",
			"label": _("Par levels"),
			"description": _("Browse department par levels you can read."),
		},
	]


def _shortcuts(roles: set[str], identity: dict) -> list[dict]:
	items = []
	if any(station["implemented"] for station in identity["stations"]):
		items.append(
			{
				"key": "station",
				"label": _("Open station"),
				"description": _("Continue work at an authorized station."),
				"route_key": "station",
				"badge": None,
			}
		)
	# Search is an entry point; search result and destination APIs authorize each resource.
	items.append(
		{
			"key": "search",
			"label": _("Scan or search"),
			"description": _("Find an instrument set, cycle, batch or equipment."),
			"route_key": "search",
			"badge": None,
		}
	)
	for target in _doctype_targets():
		if frappe.has_permission(target["doctype"], ptype="read"):
			items.append(
				{
					"key": target["key"],
					"label": target["label"],
					"description": target["description"],
					"route_key": target["key"],
					"badge": None,
				}
			)
	if identity["name"] == "Administrator" or "System Manager" in roles:
		items.append(
			{
				"key": "frappe-admin",
				"label": _("Frappe Admin"),
				"description": _("Open Frappe administration."),
				"route_key": "frappe-admin",
				"badge": None,
			}
		)
	return items


def _navigation(shortcuts: list[dict]) -> list[dict]:
	return [
		{"key": item["key"], "label": item["label"], "route_key": item["route_key"]} for item in shortcuts
	]


def _metrics() -> list[dict]:
	metrics = []
	for target in _doctype_targets():
		if not frappe.has_permission(target["doctype"], ptype="read"):
			continue
		# Unlike db.count/get_all, get_list also applies User Permissions and query conditions.
		rows = frappe.get_list(target["doctype"], fields=["count(name) as value"], order_by="")
		if rows and rows[0].get("value") is not None:
			metrics.append(
				{
					"key": target["key"],
					"label": target["label"],
					"value": int(rows[0]["value"]),
					"route_key": target["key"],
				}
			)
	return metrics


def _attention() -> list[dict]:
	# No implemented actionable aggregate is available yet; never fabricate alerts.
	return []


def _etag(payload: dict) -> str:
	stable = {key: value for key, value in payload.items() if key != "etag"}
	stable["system"] = {key: value for key, value in payload["system"].items() if key != "server_time"}
	canonical = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
	return hashlib.sha256(canonical.encode()).hexdigest()[:16]


@frappe.whitelist(methods=["GET"])
def context() -> dict:
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to open TraceCore."), frappe.PermissionError)
	roles = set(frappe.get_roles())
	identity = _identity(frappe.session.user, roles)
	shortcuts = _shortcuts(roles, identity)
	payload = {
		"user": identity,
		"capabilities": [item["route_key"] for item in shortcuts],
		"navigation": _navigation(shortcuts),
		"attention": _attention(),
		"metrics": _metrics(),
		"shortcuts": shortcuts,
		"system": {"api_version": 1, "server_time": server_time()},
	}
	payload["etag"] = _etag(payload)
	return payload
