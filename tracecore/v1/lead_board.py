"""Số liệu của khu Trưởng khoa KSNK trên Page tc-flow (FEAT-102, A-162, FR-M9-33).

Lớp API ghép số liệu đã có, không tính lại quy tắc: khối dashboard SCR-32 (`admin_reports.dashboard`), kiểm cơ số
(`v1.par.check`), kho vô khuẩn (`reprocessing.storage`), tồn khoa (`reprocessing.issuing`), sổ tiệt khuẩn và dự báo
thay thế (`admin_reports.sterilization_log`), phân bổ chi phí theo kỳ (`costing.entry`). Chỉ đọc; không trả mã người
bệnh đầy đủ (chỉ `patient_code_masked`). Hàm ở đây không kiểm quyền: RPC `tracecore.v1.lead.*` kiểm vai trò.
"""

import re
from datetime import timedelta

import frappe
from frappe.utils import add_months, cint, date_diff, flt, get_last_day, getdate, today

from tracecore.admin_reports import dashboard as board
from tracecore.admin_reports import sterilization_log as slog
from tracecore.costing import entry as cost_entry
from tracecore.reprocessing import issuing, storage
from tracecore.v1 import par

REPROCESSING = ("Processing", "Reprocess")
LOAD_WAITING = ("Cycle Complete", "Quarantine")
NC_CLOSED = ("Closed", "Cancelled")
STEAM = "Steam Sterilizer"
STERILIZERS = (STEAM, "Plasma Sterilizer")
LIST_LIMIT = 50
CERTIFICATE_DAYS = board.CERTIFICATE_DAYS
INSPECTION_DAYS = board.EQUIPMENT_DAYS
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# dòng gói của lệnh thu hồi: mã người bệnh chỉ ở dạng che (NFR-PRIV-01)
RECALL_LINE_FIELDS = [
	"parent",
	"pack",
	"set_unit",
	"department",
	"department_name",
	"status_at_recall",
	"action",
	"patient_code_masked",
	"line_status",
	"confirmed_by",
	"confirmed_at",
]


def _between(start, end):
	return ["between", [start, end - timedelta(microseconds=1)]]


def _names(doctype, names, field):
	names = [name for name in set(names) if name]
	if not names:
		return {}
	return dict(
		frappe.get_all(doctype, filters={"name": ["in", names]}, fields=["name", field], as_list=True)
	)


def _people(users):
	"""Tên người theo tài khoản: tên nhân viên nếu có, không thì họ tên của tài khoản."""
	users = [user for user in set(users) if user]
	if not users:
		return {}
	names = dict(
		frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"], as_list=True)
	)
	names.update(
		frappe.get_all(
			"Employee", filters={"user_id": ["in", users]}, fields=["user_id", "employee_name"], as_list=True
		)
	)
	return names


# --- Tổng quan hôm nay ------------------------------------------------------------------------------------------


def month_range(month):
	"""``(ngày đầu, ngày cuối)`` của tháng ``YYYY-MM``; sai định dạng → None."""
	if not isinstance(month, str) or not MONTH.match(month):
		return None
	start = getdate(f"{month}-01")
	return start, getdate(get_last_day(start))


def par_state(stock, low, high):
	"""Tồn khoa so với cơ số: ``below`` / ``within`` / ``above``; chưa đặt cơ số → ``none``."""
	if low is None and high is None:
		return "none"
	if low is not None and stock < low:
		return "below"
	if high is not None and stock > high:
		return "above"
	return "within"


def department_par():
	"""Mỗi khoa có đặt cơ số tồn khoa một dòng: tồn (gói đã cấp đang ở khoa), cơ số cộng theo loại bộ, tình trạng."""
	levels = frappe.get_all(
		"Par Level",
		filters={
			"par_kind": "Department Stock",
			"target_doctype": "Instrument Set Type",
			"is_active": 1,
			"department": ["is", "set"],
		},
		fields=["department", "min_qty", "max_qty"],
	)
	ranges = {}
	for level in levels:
		low, high = ranges.get(level.department, (0, 0))
		ranges[level.department] = (low + cint(level.min_qty), high + cint(level.max_qty))
	if not ranges:
		return []
	names = dict(
		frappe.get_all(
			"Department",
			filters={"name": ["in", list(ranges)]},
			fields=["name", "department_name"],
			as_list=True,
		)
	)
	rows = []
	for department, (low, high) in ranges.items():
		stock = sum(issuing.department_stock(department).values())
		rows.append(
			{
				"department": department,
				"department_name": names.get(department) or department,
				"stock": stock,
				"min": low,
				"max": high,
				"state": par_state(stock, low, high),
			}
		)
	return sorted(rows, key=lambda row: (row["department_name"], row["department"]))


def station_output(start, end):
	"""Số cổng Đạt theo trạm trong ``[start, end)`` kèm người đã ghi, theo số trạm."""
	rows = frappe.get_all(
		"Step Gate Result",
		filters={"result": "Pass", "recorded_at": _between(start, end), "station": ["is", "set"]},
		fields=["station", "recorded_by", "count(name) as n"],
		group_by="station, recorded_by",
		order_by=None,
	)
	if not rows:
		return []
	stations = {
		row.name: row
		for row in frappe.get_all(
			"Zone Station",
			filters={"name": ["in", list({row.station for row in rows})]},
			fields=["name", "zone_station_name", "station_no"],
		)
	}
	people = _people(row.recorded_by for row in rows)
	result = {}
	for row in rows:
		station = stations.get(row.station) or frappe._dict()
		entry = result.setdefault(
			row.station,
			{
				"station": row.station,
				"station_name": station.get("zone_station_name") or row.station,
				"station_no": cint(station.get("station_no")),
				"count": 0,
				"people": [],
			},
		)
		entry["count"] += row.n
		if row.recorded_by:
			entry["people"].append(people.get(row.recorded_by) or row.recorded_by)
	for entry in result.values():
		entry["people"].sort()
	return sorted(result.values(), key=lambda row: (row["station_no"] or 999, row["station"]))


def _load_counts(start, end):
	rows = frappe.get_all(
		"Sterilization Load",
		filters={"started_at": _between(start, end), "docstatus": ["<", 2]},
		fields=["status", "count(name) as n"],
		group_by="status",
		order_by=None,
	)
	return {row.status: row.n for row in rows}


def overview():
	"""Tổng quan hôm nay: việc cần quyết định, 8 số liệu, sản lượng theo trạm, tồn bộ tại khoa so với cơ số."""
	start, end = board.period_range("day")
	loads = _load_counts(start, end)
	states = [row["state"] for row in par.check(states=["blocked", "warn"], limit=500)["sets"]]
	sterile = storage.overview()
	return {
		"date": today(),
		"decisions": {
			"overrides": board.pending_overrides(),
			"recalls": board.open_recalls(),
			"equipment": board.equipment_attention(),
			"certificates": board.expiring_certificates(),
		},
		"kpis": {
			"reprocessing": frappe.db.count("Set Unit", {"status": ["in", REPROCESSING]}),
			"loads_today": sum(loads.values()),
			"loads_waiting": sum(loads.get(status, 0) for status in LOAD_WAITING),
			"par_blocked": states.count("blocked"),
			"par_warn": states.count("warn"),
			"sterile": sum(row["count"] for row in sterile["by_set_type"]),
			"expiring": len(sterile["expiring"]),
			"cost_per_pack": cost_summary(_load_sheets(*month_range(today()[:7])))["per_pack"],
			"open_nc": frappe.db.count(
				"Incident CAPA", {"status": ["not in", NC_CLOSED], "docstatus": ["<", 2]}
			),
		},
		"output": station_output(start, end),
		"departments": department_par(),
	}


# --- Ghi đè cơ số -----------------------------------------------------------------------------------------------


def overrides():
	"""Đề nghị ghi đè chờ duyệt (cũ nhất trước) và bộ đã đạt / sắp đạt cơ số / đang ghi đè kèm dự báo thay thế."""
	requests = frappe.get_all(
		"Par Override",
		filters={"status": "Requested"},
		fields=[
			"name",
			"set_unit",
			"set_unit_name",
			"set_type",
			"department",
			"reason",
			"requested_by",
			"requested_at",
			"cycles_used",
			"max_cycles",
		],
		order_by="requested_at asc",
		limit=LIST_LIMIT,
	)
	sets = par.check(states=["blocked", "warn", "override"], limit=LIST_LIMIT)["sets"]
	units = {
		row.name: row
		for row in frappe.get_all(
			"Set Unit",
			filters={
				"name": ["in", [row.set_unit for row in requests] + [row["set_unit"] for row in sets] or [""]]
			},
			fields=["name", "set_id", "department"],
		)
	}
	departments = _names(
		"Department",
		[row.department for row in requests] + [unit.department for unit in units.values()],
		"department_name",
	)
	types = _names("Instrument Set Type", [row.set_type for row in requests], "set_type_name")
	people = _people(row.requested_by for row in requests)
	for row in requests:
		unit = units.get(row.set_unit) or frappe._dict()
		row["set_id"] = unit.get("set_id") or row.set_unit
		row["set_name"] = types.get(row.set_type) or row.set_unit_name or row.set_type
		row["department_name"] = departments.get(row.department) or row.department
		row["requested_by_name"] = people.get(row.requested_by) or row.requested_by
	forecast = {row["set_unit"]: row for row in slog.life_forecast()}
	result = []
	for row in sets:
		unit = units.get(row["set_unit"]) or frappe._dict()
		ahead = forecast.get(row["set_unit"])
		result.append(
			{
				"set_unit": row["set_unit"],
				"set_id": unit.get("set_id") or row["set_unit"],
				"set_name": row.get("set_name") or row.get("set_type"),
				"department_name": departments.get(unit.get("department")) or unit.get("department"),
				"cycles_used": row.get("cycles_used"),
				"max_cycles": row.get("max_cycles"),
				"percent": row.get("percent"),
				"state": row["state"],
				"forecast": {"month": ahead["month"], "price": ahead["price"]} if ahead else None,
			}
		)
	return {"requests": requests, "sets": result}


# --- Thu hồi và sự cố -------------------------------------------------------------------------------------------


def recalls():
	"""Lệnh thu hồi đang mở với từng gói, và sự cố / NC chưa đóng (mới nhất trước)."""
	orders = frappe.get_all(
		"Recall Order",
		filters={"status": "Open", "docstatus": 0},
		fields=[
			"name",
			"trigger",
			"sterilization_load",
			"reason",
			"opened_at",
			"pack_count",
			"confirmed_count",
			"incident",
		],
		order_by="opened_at desc",
		limit=LIST_LIMIT,
	)
	lines = {}
	if orders:
		for line in frappe.get_all(
			"Recall Order Pack",
			filters={"parent": ["in", [order.name for order in orders]], "parenttype": "Recall Order"},
			fields=RECALL_LINE_FIELDS,
			order_by="idx asc",
		):
			lines.setdefault(line.pop("parent"), []).append(line)
	people = _people(line.confirmed_by for rows in lines.values() for line in rows)
	machines = _names("Sterilization Load", [order.sterilization_load for order in orders], "equipment_name")
	for order in orders:
		order["equipment_name"] = machines.get(order.sterilization_load)
		order["lines"] = lines.get(order.name, [])
		for line in order["lines"]:
			line["confirmed"] = line.line_status == "Confirmed"
			line["confirmed_by_name"] = people.get(line.confirmed_by) or line.confirmed_by
	incidents = frappe.get_all(
		"Incident CAPA",
		filters={"status": ["not in", NC_CLOSED], "docstatus": ["<", 2]},
		fields=["name", "incident_type", "severity", "description", "status", "occurred_at"],
		order_by="occurred_at desc",
		limit=LIST_LIMIT,
	)
	return {"orders": orders, "incidents": incidents}


# --- Giá thành tái xử lý ----------------------------------------------------------------------------------------


def _sheets(date_from, date_to, source=None):
	filters = {
		"is_recalculation": 0,
		"status": ["!=", "Cancelled"],
		"cost_date": ["between", [date_from, date_to]],
	}
	if source:
		filters["source_doctype"] = source
	return frappe.get_all(
		"Cost Sheet", filters=filters, fields=["name", "equipment", "total_cost", "pack_count"]
	)


def _load_sheets(date_from, date_to):
	"""Bảng giá thành của mẻ tiệt khuẩn trong kỳ, kèm cờ ``steam`` (máy hấp hơi nước)."""
	sheets = _sheets(date_from, date_to, "Sterilization Load")
	kinds = _names("Equipment", [sheet.equipment for sheet in sheets], "equipment_type")
	for sheet in sheets:
		sheet["steam"] = int(kinds.get(sheet.equipment) == STEAM)
	return sheets


def cost_summary(sheets):
	"""Chi phí trung bình một mẻ hấp hơi nước và một gói (tổng chi phí ÷ tổng số gói), VND không lẻ."""
	steam = [flt(sheet.total_cost) for sheet in sheets if sheet.get("steam")]
	packs = sum(cint(sheet.pack_count) for sheet in sheets)
	total = sum(flt(sheet.total_cost) for sheet in sheets)
	return {
		"per_load": cint(round(sum(steam) / len(steam))) if steam else 0,
		"per_pack": cint(round(total / packs)) if packs else 0,
		"packs": packs,
		"loads": len(sheets),
	}


def change_pct(current, previous):
	"""Thay đổi so với kỳ trước (%), một chữ số thập phân; kỳ trước không có số → None."""
	if not previous:
		return None
	return round((current - previous) * 100 / previous, 1)


def _components(date_from, date_to):
	names = [sheet.name for sheet in _sheets(date_from, date_to)]
	if not names:
		return []
	rows = frappe.get_all(
		"Cost Sheet Line",
		filters={"parent": ["in", names], "parenttype": "Cost Sheet"},
		fields=["component", "sum(amount) as amount"],
		group_by="component",
		order_by=None,
	)
	total = sum(flt(row.amount) for row in rows)
	result = [
		{
			"component": row.component,
			"amount": cint(round(flt(row.amount))),
			"share": round(flt(row.amount) * 100 / total, 1) if total else 0,
		}
		for row in rows
	]
	return sorted(result, key=lambda row: -row["amount"])


def _set_types(date_from, date_to):
	names = [sheet.name for sheet in _sheets(date_from, date_to)]
	if not names:
		return []
	rows = frappe.get_all(
		"Cost Sheet Pack",
		filters={"parent": ["in", names], "parenttype": "Cost Sheet", "set_type": ["is", "set"]},
		fields=["set_type", "count(name) as packs", "sum(total) as total"],
		group_by="set_type",
		order_by=None,
	)
	labels = _names("Instrument Set Type", [row.set_type for row in rows], "set_type_name")
	result = [
		{
			"set_type": row.set_type,
			"set_name": labels.get(row.set_type) or row.set_type,
			"packs": cint(row.packs),
			"total": cint(round(flt(row.total))),
			"average": cint(round(flt(row.total) / row.packs)) if row.packs else 0,
		}
		for row in rows
	]
	return sorted(result, key=lambda row: (row["set_name"], row["set_type"]))


def _inputs(date_from, date_to):
	"""Chi phí đầu vào đã ghi sổ, phần rơi vào kỳ (chia theo ngày như FR-M7-01.2), cộng theo khoản mục và nguồn."""
	entries = frappe.get_all(
		"Cost Entry",
		filters={"docstatus": 1, "period_from": ["<=", date_to], "period_to": [">=", date_from]},
		fields=["category", "source", "amount", "period_from", "period_to"],
	)
	totals = {}
	for row in entries:
		key = (row.category, row.source)
		totals[key] = totals.get(key, 0) + cost_entry.amount_in(row, date_from, date_to)
	result = [
		{"category": category, "source": source, "amount": amount}
		for (category, source), amount in totals.items()
		if amount
	]
	return sorted(result, key=lambda row: -row["amount"])


def costs(month):
	"""Giá thành của tháng ``YYYY-MM`` (đã kiểm định dạng) so với tháng liền trước."""
	date_from, date_to = month_range(month)
	now = cost_summary(_load_sheets(date_from, date_to))
	before_from = getdate(add_months(date_from, -1))
	before = cost_summary(_load_sheets(before_from, getdate(get_last_day(before_from))))
	return {
		"month": month,
		**now,
		# tháng chưa có gói nào được tính giá thì không so sánh (không hiện mức giảm 100 %)
		"change_pct": change_pct(now["per_pack"], before["per_pack"]) if now["packs"] else None,
		"components": _components(date_from, date_to),
		"set_types": _set_types(date_from, date_to),
		"inputs": _inputs(date_from, date_to),
	}


# --- Thiết bị và test hằng ngày ---------------------------------------------------------------------------------


def equipment():
	"""Máy chưa thanh lý: trạng thái, nguồn dữ liệu chu trình, test hôm nay, hạn kiểm định, chương trình đang dùng."""
	machines = frappe.get_all(
		"Equipment",
		filters={"status": ["!=", "Retired"]},
		fields=[
			"name",
			"equipment_name",
			"equipment_type",
			"model",
			"capacity",
			"status",
			"lock_reason",
			"is_connected",
			"has_printout",
			"daily_test_required",
			"inspection_due",
		],
		order_by="name asc",
	)
	names = [machine.name for machine in machines] or [""]
	tests, programs = {}, {}
	for row in frappe.get_all(
		"Daily Test",
		filters={"equipment": ["in", names], "test_date": today(), "docstatus": ["<", 2]},
		fields=["equipment", "test_type", "result", "run_status", "tested_at"],
		order_by="creation asc",
	):
		tests.setdefault(row.pop("equipment"), []).append(row)
	for row in frappe.get_all(
		"Process Program",
		filters={"equipment": ["in", names], "is_active": 1, "program_kind": ["!=", "Test"]},
		fields=["equipment", "program_name"],
		order_by="program_name asc",
	):
		programs.setdefault(row.equipment, []).append(row.program_name)
	for machine in machines:
		days = date_diff(machine.inspection_due, today()) if machine.inspection_due else None
		machine["inspection_days"] = days
		machine["expiring"] = days is not None and days <= INSPECTION_DAYS
		machine["tests"] = tests.get(machine.name, [])
		machine["programs"] = programs.get(machine.name, [])
	return {"date": today(), "rows": machines}


# --- Nhân sự, chứng chỉ và năng lực trạm ------------------------------------------------------------------------


def staff_state(certificates, on=None):
	"""Tình trạng chứng chỉ của một người: ``(none | expired | expiring | ok, số ngày còn lại của hạn gần nhất)``."""
	day = getdate(on or today())
	rows = [row for row in certificates if row.get("status") in ("Valid", "Expired")]
	if not rows:
		return "none", None
	days = [
		date_diff(row["expires_on"], day)
		for row in rows
		if row.get("expires_on") and not row.get("no_expiry")
	]
	nearest = min(days) if days else None
	if any(row.get("status") == "Expired" for row in rows) or (nearest is not None and nearest < 0):
		return "expired", nearest
	if nearest is not None and nearest <= CERTIFICATE_DAYS:
		return "expiring", nearest
	return "ok", nearest


def staff():
	"""Nhân viên đang làm có chứng chỉ hoặc năng lực trạm: chứng chỉ, hạn gần nhất, trạm được làm, tình trạng."""
	certificates, stations = {}, {}
	for row in frappe.get_all(
		"Certificate",
		filters={"status": ["in", ["Valid", "Expired"]]},
		fields=["employee", "certificate_type", "certificate_no", "status", "expires_on", "no_expiry"],
		order_by="expires_on asc",
	):
		certificates.setdefault(row.employee, []).append(row)
	for row in frappe.get_all(
		"Station Competency",
		filters={"is_active": 1},
		fields=["employee", "station", "station_name", "valid_until"],
	):
		if not row.valid_until or getdate(row.valid_until) >= getdate(today()):
			stations.setdefault(row.employee, []).append(row)
	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active", "name": ["in", list(set(certificates) | set(stations)) or [""]]},
		fields=["name", "employee_name", "designation"],
		order_by="employee_name asc",
	)
	numbers = _names(
		"Zone Station", [row.station for rows in stations.values() for row in rows], "station_no"
	)
	result = []
	for employee in employees:
		own = certificates.get(employee.name, [])
		state, days = staff_state(own)
		dated = [row.expires_on for row in own if row.expires_on and not row.no_expiry]
		result.append(
			{
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"designation": employee.designation,
				"certificates": [
					" ".join(part for part in (row.certificate_type, row.certificate_no) if part)
					for row in own
				],
				"expires_on": min(dated) if dated else None,
				"state": state,
				"days_left": days,
				"stations": sorted(
					(
						{
							"station": row.station,
							"station_name": row.station_name or row.station,
							"station_no": cint(numbers.get(row.station)),
						}
						for row in stations.get(employee.name, [])
					),
					key=lambda row: (row["station_no"] or 999, row["station"]),
				),
			}
		)
	return {"rows": result}


# --- Sổ tiệt khuẩn điện tử --------------------------------------------------------------------------------------


def sterilizers():
	return frappe.get_all(
		"Equipment",
		filters={"equipment_type": ["in", STERILIZERS], "status": ["!=", "Retired"]},
		fields=["name", "equipment_name"],
		order_by="name asc",
	)


def sterilization_log(equipment, date):
	"""Các mẻ đã kết thúc của ``equipment`` (bỏ trống = mọi máy) trong ngày ``date`` (YYYY-MM-DD đã kiểm)."""
	return {
		"date": date,
		"equipment": equipment,
		"machines": sterilizers(),
		"rows": slog.log_rows({"from_date": date, "to_date": date, "equipment": equipment}),
	}
