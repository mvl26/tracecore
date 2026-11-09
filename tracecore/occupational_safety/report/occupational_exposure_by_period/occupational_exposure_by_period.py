"""Occupational Exposure by Period — "Phơi nhiễm theo kỳ" (FEAT-071; FR-M16-09, FR-M16-09.1; BRU-OCC-003; NFR-PRIV-01).

Tổng hợp hồ sơ phơi nhiễm (trừ Cancelled) theo loại, khoa, nghề nghiệp hoặc thiết bị: số ca, tỷ lệ báo đúng hạn,
tỷ lệ hoàn thành theo dõi. Chỉ số liệu: không tên nhân viên, không mã BN nguồn. ``ref_doctype`` là IC Indicator Value
để R13 (chỉ đọc số liệu tổng hợp) mở được mà không có quyền đọc hồ sơ cá nhân.
"""

import frappe
from frappe import _
from frappe.utils import get_first_day, getdate, nowdate

DOCTYPE = "Occupational Exposure"
GROUPS = {
	"Exposure Type": "exposure_type",
	"Department": "department",
	"Occupation": "occupation",
	"Device": "device",
}
TRANSLATED = ("exposure_type",)


def _columns(group_by):
	return [
		{"fieldname": "group", "label": _(group_by), "fieldtype": "Data", "width": 240},
		{"fieldname": "exposures", "label": _("Exposures"), "fieldtype": "Int", "width": 110},
		{"fieldname": "on_time", "label": _("Reported on Time"), "fieldtype": "Int", "width": 140},
		{"fieldname": "on_time_rate", "label": _("On-time Report Rate (%)"), "fieldtype": "Percent", "width": 170},
		{"fieldname": "scheduled", "label": _("With Follow-up Schedule"), "fieldtype": "Int", "width": 170},
		{"fieldname": "completed", "label": _("Follow-up Completed"), "fieldtype": "Int", "width": 160},
		{"fieldname": "completion_rate", "label": _("Follow-up Completion Rate (%)"), "fieldtype": "Percent", "width": 200},
	]


def _rate(part, whole):
	return round(100.0 * part / whole, 1) if whole else None


def _row(group, items):
	scheduled = [r for r in items if r.followup_template]
	on_time = sum(1 for r in items if not r.report_late)
	completed = sum(1 for r in scheduled if r.status == "Completed")
	return {
		"group": group,
		"exposures": len(items),
		"on_time": on_time,
		"on_time_rate": _rate(on_time, len(items)),
		"scheduled": len(scheduled),
		"completed": completed,
		"completion_rate": _rate(completed, len(scheduled)),
	}


def _label(field, value):
	if not value:
		return _("Not specified")
	if field in TRANSLATED:
		return _(value, context=DOCTYPE)
	if field == "department":
		return frappe.db.get_value("Department", value, "department_name") or value
	return value


def execute(filters=None):
	filters = frappe._dict(filters or {})
	group_by = filters.get("group_by") if filters.get("group_by") in GROUPS else "Exposure Type"
	field = GROUPS[group_by]
	start = getdate(filters.get("from_date") or get_first_day(nowdate()).replace(month=1))
	end = getdate(filters.get("to_date") or nowdate())
	rows = frappe.get_all(
		DOCTYPE,
		filters={
			"status": ["!=", "Cancelled"],
			"occurred_at": ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]],
		},
		fields=[field, "status", "report_late", "followup_template"],
	)
	buckets = {}
	for row in rows:
		buckets.setdefault(row.get(field) or "", []).append(row)
	data = [_row(_label(field, key), items) for key, items in sorted(buckets.items(), key=lambda kv: -len(kv[1]))]
	if rows:
		data.append({**_row(_("Total"), rows), "bold": 1})
	return _columns(group_by), data
