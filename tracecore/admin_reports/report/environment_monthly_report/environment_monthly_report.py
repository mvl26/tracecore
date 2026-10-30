"""Báo cáo tháng môi trường khu (FEAT-008, FR-M9-04, A-55 D5).

Mỗi dòng là một khu trong một ngày của tháng (tới hôm nay): số lần đo đã ghi sổ, nhỏ nhất/lớn nhất của nhiệt độ, độ
ẩm, áp suất chênh, số lần vượt ngưỡng và số mốc giờ nhắc không có lần đo (khung như `environment.remind_missing`; mốc
của hôm nay chỉ tính khi đã qua). Khu = khu đang theo dõi và khu có lần đo trong tháng. In và xuất Excel bằng công cụ
chuẩn của Report.
"""

import calendar
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime

from tracecore.admin_reports import environment

STATS = (("temperature", "temp"), ("humidity", "humidity"), ("pressure_diff", "pressure"))


def _columns():
	columns = [
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "zone",
			"label": _("Zone"),
			"fieldtype": "Link",
			"options": "Zone Station",
			"width": 110,
		},
		{"fieldname": "zone_name", "label": _("Zone Name"), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "readings",
			"label": _("Readings", context="Environment Log"),
			"fieldtype": "Int",
			"width": 80,
		},
	]
	labels = {
		"temp": (_("Min Temperature (°C)"), _("Max Temperature (°C)")),
		"humidity": (_("Min Humidity (%)"), _("Max Humidity (%)")),
		"pressure": (_("Min Pressure Difference (Pa)"), _("Max Pressure Difference (Pa)")),
	}
	for _field, key in STATS:
		low, high = labels[key]
		columns.append({"fieldname": f"{key}_min", "label": low, "fieldtype": "Float", "width": 110})
		columns.append({"fieldname": f"{key}_max", "label": high, "fieldtype": "Float", "width": 110})
	columns += [
		{"fieldname": "out_of_range", "label": _("Out of Range"), "fieldtype": "Int", "width": 90},
		{"fieldname": "missing", "label": _("Missing Times"), "fieldtype": "Int", "width": 90},
	]
	return columns


def _period(filters):
	month, year = cint(filters.get("month")), cint(filters.get("year"))
	if not 1 <= month <= 12 or not year:
		frappe.throw(_("Choose a month and a year."))
	return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _zones(filters, readings):
	if filters.get("zone"):
		names = [filters.zone]
	else:
		names = frappe.get_all(
			"Zone Station", filters={"is_zone": 1, "env_monitored": 1}, pluck="name", order_by="name"
		)
		names += sorted({row.zone for row in readings} - set(names))
	titles = dict(
		frappe.get_all(
			"Zone Station",
			filters={"name": ["in", names or [""]]},
			fields=["name", "zone_station_name"],
			as_list=True,
		)
	)
	return [(name, titles.get(name) or name) for name in names]


def _missing(zone_readings, day, times, now):
	count = 0
	for start, end in environment.windows(day, times):
		if end > now:
			break
		if not any(start <= row.measured_at < end for row in zone_readings):
			count += 1
	return count


def execute(filters=None):
	filters = frappe._dict(filters or {})
	first, last = _period(filters)
	now = now_datetime()
	last = min(last, getdate(now))
	conditions = [["docstatus", "=", 1], ["log_date", "between", [first, last]]]
	if filters.get("zone"):
		conditions.append(["zone", "=", filters.zone])
	readings = frappe.get_all(
		"Environment Log",
		filters=conditions,
		fields=[
			"zone",
			"log_date",
			"measured_at",
			"temperature",
			"humidity",
			"pressure_diff",
			"out_of_range",
		],
		order_by="measured_at asc",
	)
	times = environment.reminder_times()
	by_day = {}
	for row in readings:
		by_day.setdefault((row.zone, getdate(row.log_date)), []).append(row)
	data = []
	for zone, title in _zones(filters, readings):
		day = first
		while day <= last:
			rows = by_day.get((zone, day), [])
			line = {
				"date": day,
				"zone": zone,
				"zone_name": title,
				"readings": len(rows),
				"out_of_range": sum(cint(row.out_of_range) for row in rows),
				"missing": _missing(rows, day, times, now),
			}
			for field, key in STATS:
				values = [environment.to_number(row.get(field), field) for row in rows]
				values = [value for value in values if value is not None]
				line[f"{key}_min"] = min(values) if values else None
				line[f"{key}_max"] = max(values) if values else None
			data.append(line)
			day = date.fromordinal(day.toordinal() + 1)
	return _columns(), data
