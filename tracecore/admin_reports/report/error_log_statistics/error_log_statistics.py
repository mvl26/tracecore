"""Thống kê Nhật ký lỗi (FEAT-052, A-71, FR-M9-20): số lần phát sinh theo mã và trạm trong kỳ, cho R01."""

import frappe
from frappe import _

_STATUS_KEYS = {"Open": "open", "Resolved": "resolved", "Temporarily Allowed": "allowed"}


def _columns():
	return [
		{
			"fieldname": "error_code",
			"label": _("Code"),
			"fieldtype": "Link",
			"options": "TraceCore Error Code",
			"width": 90,
		},
		{"fieldname": "error_name", "label": _("Name"), "fieldtype": "Data", "width": 260},
		{
			"fieldname": "station",
			"label": _("Station"),
			"fieldtype": "Link",
			"options": "Zone Station",
			"width": 160,
		},
		{"fieldname": "total", "label": _("Occurrences"), "fieldtype": "Int", "width": 110},
		{"fieldname": "open", "label": _("Open"), "fieldtype": "Int", "width": 80},
		{"fieldname": "resolved", "label": _("Resolved"), "fieldtype": "Int", "width": 90},
		{"fieldname": "allowed", "label": _("Temporarily allowed"), "fieldtype": "Int", "width": 130},
	]


def execute(filters=None):
	filters = filters or {}
	conditions = {}
	if filters.get("from_date") and filters.get("to_date"):
		conditions["occurred_at"] = [
			"between",
			[f"{filters['from_date']} 00:00:00", f"{filters['to_date']} 23:59:59"],
		]
	for field in ("error_code", "station"):
		if filters.get(field):
			conditions[field] = filters[field]
	rows = {}
	for log in frappe.get_all(
		"TraceCore Error Log", filters=conditions, fields=["error_code", "station", "status"]
	):
		row = rows.setdefault(
			(log.error_code, log.station or ""),
			{
				"error_code": log.error_code,
				"station": log.station,
				"total": 0,
				"open": 0,
				"resolved": 0,
				"allowed": 0,
			},
		)
		row["total"] += 1
		row[_STATUS_KEYS[log.status]] += 1
	names = dict(frappe.get_all("TraceCore Error Code", fields=["name", "error_name"], as_list=True))
	result = sorted(rows.values(), key=lambda row: (-row["total"], row["error_code"]))
	for row in result:
		row["error_name"] = _(names.get(row["error_code"]) or "")
	return _columns(), result
