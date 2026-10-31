"""Danh mục mã lỗi theo trạm (FEAT-052, A-71, FR-M9-21): tài liệu HDSD in được, lọc theo trạm hoặc mã."""

import frappe
from frappe import _
from frappe.utils.html_utils import clean_html


def _columns():
	return [
		{
			"fieldname": "code",
			"label": _("Code"),
			"fieldtype": "Link",
			"options": "TraceCore Error Code",
			"width": 90,
		},
		{"fieldname": "error_name", "label": _("Name"), "fieldtype": "Data", "width": 240},
		{"fieldname": "severity", "label": _("Severity"), "fieldtype": "Data", "width": 90},
		{"fieldname": "enabled", "label": _("Enabled"), "fieldtype": "Data", "width": 80},
		{"fieldname": "stations", "label": _("Stations"), "fieldtype": "Data", "width": 220},
		{"fieldname": "trigger_condition", "label": _("Condition"), "fieldtype": "Data", "width": 280},
		{"fieldname": "system_action", "label": _("System action"), "fieldtype": "Data", "width": 240},
		{"fieldname": "release", "label": _("How it clears"), "fieldtype": "Data", "width": 120},
		{"fieldname": "guide", "label": _("Handling guide"), "fieldtype": "HTML", "width": 320},
	]


def _rules():
	settings = frappe.get_cached_doc("TraceCore Settings")
	return {row.error_code: row for row in settings.get("error_rules") or []}


def _station_label(key):
	if key == "LOGIN":
		return _("Login")
	return _(frappe.db.get_value("Station Function", key, "function_name") or key)


def _matching_codes(filters):
	conditions = {}
	if filters.get("code"):
		conditions["name"] = filters["code"]
	codes = frappe.get_all("TraceCore Error Code", filters=conditions, pluck="name", order_by="name")
	if not filters.get("station"):
		return codes
	at_station = set(
		frappe.get_all(
			"TraceCore Error Code Station", filters={"station_key": filters["station"]}, pluck="parent"
		)
	)
	return [code for code in codes if code in at_station]


def execute(filters=None):
	filters = filters or {}
	rules = _rules()
	rows = []
	for code in _matching_codes(filters):
		doc = frappe.get_doc("TraceCore Error Code", code)
		rule = rules.get(code)
		rows.append(
			{
				"code": code,
				"error_name": _(doc.error_name),
				"severity": _((rule.severity if rule else None) or doc.default_severity),
				"enabled": _("Yes") if not rule or rule.enabled else _("No"),
				"stations": ", ".join(_station_label(row.station_key) for row in doc.stations),
				"trigger_condition": doc.trigger_condition,
				"system_action": doc.system_action,
				"release": _("Clears when fixed") if doc.release_method == "Auto" else _("Approval possible"),
				"guide": clean_html(doc.guide or ""),
			}
		)
	return _columns(), rows
