"""Số liệu tổng hợp cho dashboard vận hành SCR-32 (FEAT-006, FR-M9-01, FR-M9-01.2, UC-32; A-54).

Chỉ truy vấn theo tên DocType bằng ``GROUP BY`` (không import module nghiệp vụ khác, R1). Không có dữ liệu thì trả 0
hoặc danh sách rỗng, không ném. Hàm không kiểm quyền: RPC ``tracecore.v1.dashboard.summary`` chọn khối theo vai trò.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, getdate, now_datetime, today

SET_STATUSES = (
	"New",
	"In Circulation",
	"Processing",
	"Reprocess",
	"Sterile",
	"At Department",
	"Awaiting Receipt",
	"End of Life",
	"Disposed",
	"Returned",
)
PERIODS = ("day", "week", "month")
# D5: mẻ đã kết thúc (có kết luận); mẻ đang chạy/chờ dỡ không tính vào mẫu số
LOAD_FINISHED = ("Released", "Failed", "Quarantine")
WASH_FINISHED = ("Passed", "Failed")
TOP = 10
LIST_LIMIT = 5
CERTIFICATE_DAYS = 60
EQUIPMENT_DAYS = 30


def period_range(period, on=None):
	"""Khoảng ``[start, end)`` của kỳ ``day`` / ``week`` (thứ Hai đến Chủ nhật) / ``month`` chứa thời điểm `on` (giờ hệ thống)."""
	if period not in PERIODS:
		frappe.throw(_("Period must be one of {0}.").format(", ".join(PERIODS)))
	day = getdate(on or now_datetime())
	start = datetime(day.year, day.month, day.day)
	if period == "day":
		return start, start + timedelta(days=1)
	if period == "week":
		start -= timedelta(days=start.weekday())
		return start, start + timedelta(days=7)
	start = start.replace(day=1)
	end = (
		start.replace(year=start.year + 1, month=1)
		if start.month == 12
		else start.replace(month=start.month + 1)
	)
	return start, end


def set_status_counts(department=None):
	"""Số bộ theo từng trạng thái, đủ `SET_STATUSES` theo thứ tự (thiếu = 0); `department` lọc theo khoa của bộ."""
	filters = {"department": department} if department else {}
	rows = frappe.get_all(
		"Set Unit", filters=filters, fields=["status", "count(name) as n"], group_by="status", order_by=None
	)
	counts = {row.status: row.n for row in rows}
	return [{"status": status, "count": counts.get(status, 0)} for status in SET_STATUSES]


def _stations_of(zone):
	return frappe.get_all("Zone Station", filters={"parent_zone": zone, "is_zone": 0}, pluck="name")


def _gate_filters(start, end, zone):
	filters = {"result": "Pass", "recorded_at": ["between", [start, end - timedelta(microseconds=1)]]}
	if zone:
		filters["station"] = ["in", _stations_of(zone) or [""]]
	return filters


def output_by_station(start, end, zone=None, limit=TOP):
	"""Số cổng Đạt theo trạm trong ``[start, end)``, nhiều nhất trước (D4)."""
	rows = frappe.get_all(
		"Step Gate Result",
		filters=_gate_filters(start, end, zone),
		fields=["station", "count(name) as n"],
		group_by="station",
		order_by="n desc, station asc",
		limit=limit,
	)
	names = dict(
		frappe.get_all(
			"Zone Station",
			filters={"name": ["in", [row.station for row in rows] or [""]]},
			fields=["name", "zone_station_name"],
			as_list=True,
		)
	)
	return [
		{"station": row.station, "station_name": names.get(row.station) or row.station, "count": row.n}
		for row in rows
		if row.station
	]


def output_by_user(start, end, zone=None, limit=TOP):
	"""Số cổng Đạt theo người ghi (`recorded_by`) trong ``[start, end)``, nhiều nhất trước (D4)."""
	rows = frappe.get_all(
		"Step Gate Result",
		filters=_gate_filters(start, end, zone),
		fields=["recorded_by", "count(name) as n"],
		group_by="recorded_by",
		order_by="n desc, recorded_by asc",
		limit=limit,
	)
	names = dict(
		frappe.get_all(
			"User",
			filters={"name": ["in", [row.recorded_by for row in rows] or [""]]},
			fields=["name", "full_name"],
			as_list=True,
		)
	)
	return [
		{"user": row.recorded_by, "full_name": names.get(row.recorded_by) or row.recorded_by, "count": row.n}
		for row in rows
		if row.recorded_by
	]


def _count_by_equipment(doctype, start, end, equipment, statuses=None):
	filters = {
		"started_at": ["between", [start, end - timedelta(microseconds=1)]],
		"equipment": ["is", "set"],
	}
	if equipment:
		filters["equipment"] = equipment
	if statuses:
		filters["status"] = ["in", statuses]
	rows = frappe.get_all(
		doctype,
		filters=filters,
		fields=["equipment", "count(name) as n"],
		group_by="equipment",
		order_by=None,
	)
	return {row.equipment: row.n for row in rows}


def output_by_equipment(start, end, zone=None, equipment=None, limit=TOP):
	"""Số lô rửa và mẻ tiệt khuẩn bắt đầu trong ``[start, end)`` theo máy, nhiều nhất trước (D4)."""
	wash = _count_by_equipment("Wash Batch", start, end, equipment)
	load = _count_by_equipment("Sterilization Load", start, end, equipment)
	names = set(wash) | set(load)
	if not names:
		return []
	machines = {
		row.name: row
		for row in frappe.get_all(
			"Equipment", filters={"name": ["in", list(names)]}, fields=["name", "equipment_name", "zone_in"]
		)
	}
	rows = [
		{
			"equipment": name,
			"equipment_name": machines[name].equipment_name if name in machines else name,
			"wash": wash.get(name, 0),
			"load": load.get(name, 0),
			"count": wash.get(name, 0) + load.get(name, 0),
		}
		for name in names
		if not zone or (name in machines and machines[name].zone_in == zone)
	]
	rows.sort(key=lambda row: (-row["count"], row["equipment"]))
	return rows[:limit]


def _rate(doctype, start, end, equipment, finished):
	counts = _count_by_status(doctype, start, end, equipment)
	done = sum(counts.get(status, 0) for status in finished)
	failed = counts.get("Failed", 0)
	return {"failed": failed, "finished": done, "percent": round(failed * 100 / done, 1) if done else 0}


def _count_by_status(doctype, start, end, equipment):
	filters = {"started_at": ["between", [start, end - timedelta(microseconds=1)]]}
	if equipment:
		filters["equipment"] = equipment
	rows = frappe.get_all(
		doctype, filters=filters, fields=["status", "count(name) as n"], group_by="status", order_by=None
	)
	return {row.status: row.n for row in rows}


def failure_rates(start, end, equipment=None):
	"""Tỷ lệ mẻ lỗi trong ``[start, end)`` (D5): hấp = Failed ÷ (Released + Failed + Quarantine), rửa = Failed ÷ (Passed +
	Failed); không có mẻ kết thúc → 0."""
	return {
		"load": _rate("Sterilization Load", start, end, equipment, LOAD_FINISHED),
		"wash": _rate("Wash Batch", start, end, equipment, WASH_FINISHED),
	}


def _listing(doctype, filters, fields, order_by, limit):
	return {
		"count": frappe.db.count(doctype, filters),
		"rows": frappe.get_all(doctype, filters=filters, fields=fields, order_by=order_by, limit=limit),
	}


def pending_overrides(limit=LIST_LIMIT):
	"""Đề nghị ghi đè cơ số chờ duyệt (`Par Override` Requested), cũ nhất trước (D7)."""
	return _listing(
		"Par Override",
		{"status": "Requested"},
		["name", "set_unit", "set_type", "department", "reason", "requested_at"],
		"requested_at asc",
		limit,
	)


def open_recalls(limit=LIST_LIMIT):
	"""Lệnh thu hồi đang mở còn gói chưa xác nhận (D7); số lệnh mở nhỏ nên lọc so sánh hai cột trong Python."""
	rows = frappe.get_all(
		"Recall Order",
		filters={"status": "Open"},
		fields=["name", "trigger", "sterilization_load", "pack_count", "confirmed_count", "opened_at"],
		order_by="opened_at asc",
	)
	rows = [row for row in rows if (row.confirmed_count or 0) < (row.pack_count or 0)]
	return {"count": len(rows), "rows": rows[:limit]}


def expiring_certificates(days=CERTIFICATE_DAYS, limit=LIST_LIMIT):
	"""Chứng chỉ của nhân viên đang làm: hết hạn (Expired) hoặc còn hiệu lực nhưng hết hạn trong `days` ngày (D7)."""
	active = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")
	if not active:
		return {"count": 0, "rows": []}
	rows = frappe.get_all(
		"Certificate",
		filters={
			"employee": ["in", active],
			"no_expiry": 0,
			"status": ["in", ["Valid", "Expired"]],
			"expires_on": ["<=", add_days(today(), days)],
		},
		fields=["name", "employee", "employee_name", "certificate_type", "expires_on", "status"],
		order_by="expires_on asc",
	)
	for row in rows:
		row["days_left"] = date_diff(row.expires_on, today())
	return {"count": len(rows), "rows": rows[:limit]}


def equipment_attention(days=EQUIPMENT_DAYS, limit=LIST_LIMIT):
	"""Máy khóa / đang sửa, hoặc kiểm định, hiệu chuẩn hết hạn trong `days` ngày; bỏ máy thanh lý (D7)."""
	horizon = getdate(add_days(today(), days))
	rows = frappe.get_all(
		"Equipment",
		filters={"status": ["!=", "Retired"]},
		fields=[
			"name",
			"equipment_name",
			"equipment_type",
			"status",
			"lock_reason",
			"inspection_due",
			"calibration_due",
		],
	)
	result = []
	for row in rows:
		dues = [getdate(d) for d in (row.inspection_due, row.calibration_due) if d]
		nearest = min(dues) if dues else None
		if row.status in ("Locked", "Repair") or (nearest and nearest <= horizon):
			row["due_in"] = date_diff(nearest, today()) if nearest else None
			result.append(row)
	result.sort(
		key=lambda row: (
			row.status not in ("Locked", "Repair"),
			row["due_in"] if row["due_in"] is not None else 0,
		)
	)
	return {"count": len(result), "rows": result[:limit]}
