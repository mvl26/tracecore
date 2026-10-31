"""Rà soát chỉ đọc: máy in và Station Agent của từng trạm (ticket T2 31/10/2026, mục 4; A-72).

Không ghi gì. Dùng để biết trạm nào còn thiếu máy in đang hoạt động hoặc chưa có user agent trước khi cấu hình tay::

    bench --site <site> execute tracecore.setup.survey.printers
"""

import json

import frappe

from tracecore.core import print as core_print
from tracecore.setup.provision import agent_user_email

NO_PRINTER = "NO_ACTIVE_PRINTER"
NO_AGENT_USER = "NO_AGENT_USER"
NO_HOST = "PRINTER_WITHOUT_HOST"


def printers():
	"""Từng trạm (không tính khu): trạm, đang hoạt động, máy in active, user agent, và các vấn đề phát hiện được."""
	rows = []
	for station in frappe.get_all(
		"Zone Station",
		filters={"is_zone": 0},
		fields=["name", "zone_station_name", "is_active"],
		order_by="name asc",
	):
		active = core_print.station_printers(station.name)
		email = agent_user_email(station.name)
		has_agent = int(bool(frappe.db.get_value("User", {"name": email, "enabled": 1})))
		problems = []
		if not active:
			problems.append(NO_PRINTER)
		elif not any(printer["host"] for printer in active):
			problems.append(NO_HOST)  # không host = agent ghi file thay vì gửi máy in
		if not has_agent:
			problems.append(NO_AGENT_USER)
		rows.append(
			{
				"station": station.name,
				"station_name": station.zone_station_name,
				"is_active": int(station.is_active or 0),
				"printers": active,
				"agent_user": email,
				"has_agent_user": has_agent,
				"problems": problems,
			}
		)
	return rows


def report():
	"""Như `printers` nhưng in ra dạng bảng dễ đọc trên terminal."""
	rows = printers()
	for row in rows:
		names = ", ".join(f"{p['name']}@{p['host'] or '(file)'}" for p in row["printers"]) or "-"
		print(
			f"{row['station']:8} active={row['is_active']} printers={names} agent={row['has_agent_user']} {row['problems']}"
		)
	return json.loads(json.dumps(rows, default=str))
