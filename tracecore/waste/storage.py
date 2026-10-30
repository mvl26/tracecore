"""Kho lưu giữ tạm chất thải (FEAT-048, UC-35, FR-M10-03, .1-.4, BRU-WST-001, BRU-WST-002, A-61).

Giờ lưu luôn tính từ lúc thu gom. `store` đưa túi vào vị trí `KE-` đúng loại và tính lại hạn theo điều kiện lưu; chuyển
vị trí cũng đi đường này. `run_checks` (scheduler 15 phút) xét nhiệt độ kho lạnh rồi hạn lưu: đạt ngưỡng cảnh báo báo
R07/R02, quá hạn báo đỏ và tạo NC qua hook. Nhiệt độ là `Environment Log` của khu gắn với kho lạnh; lần đo mới nhất còn
vượt ngưỡng thì coi là vẫn vượt, nên 2 lần đo thủ công cách xa nhau vẫn phát hiện được. Ngưỡng ở `TraceCore Settings`.
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, cstr, flt, get_datetime, now_datetime

from tracecore.core import extension, notification
from tracecore.core.errors import Block, BlockedError
from tracecore.waste.collection import COLLECTED, HELD, NC_HOOK

STORED = "Stored"
LOCATION = "Waste Storage Location"
LOCATION_TYPE = "Waste Storage Location Type"
CONTAINER = "Waste Container"
SETTINGS = "TraceCore Settings"
DUE_EVENT = "WASTE_STORAGE_DUE"
OVERDUE_EVENT = "WASTE_STORAGE_OVERDUE"
COLD_EVENT = "WASTE_COLD_BREACH"
DEFAULT_WARN_PERCENT = 80
DEFAULT_COLD_LIMIT_C = 8
DEFAULT_BREACH_HOURS = 2
DEFAULT_VARIANCE_PERCENT = 5
READING_WINDOW = 100
OK, DUE_SOON, OVERDUE = "OK", "Due Soon", "Overdue"
NOTICE_CODES = 10
STOCK_LINK = "/app/query-report/Waste Storage Stock"


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


# --- ngưỡng -----------------------------------------------------------------------------------------------------------


def thresholds():
	"""Ngưỡng đang dùng; ô chưa đặt (Single trả 0) lấy mặc định của FR-M10-03.2, .3."""
	get = frappe.db.get_single_value
	return {
		"warn_percent": cint(get(SETTINGS, "waste_warn_percent")) or DEFAULT_WARN_PERCENT,
		"cold_limit_c": flt(get(SETTINGS, "waste_cold_limit_c")) or DEFAULT_COLD_LIMIT_C,
		"breach_hours": flt(get(SETTINGS, "waste_cold_breach_hours")) or DEFAULT_BREACH_HOURS,
		"variance_percent": flt(get(SETTINGS, "waste_variance_percent")) or DEFAULT_VARIANCE_PERCENT,
	}


def _threshold_number(value):
	text = cstr(value).strip().replace(",", ".")
	try:
		return float(text)
	except ValueError:
		return None


def set_thresholds(warn_percent, cold_limit_c, breach_hours, variance_percent=None):
	"""R02/R10 hiệu chỉnh ngưỡng (UC-35 Open issues); lưu qua document để có Audit Log."""
	percent, limit, hours = (_threshold_number(value) for value in (warn_percent, cold_limit_c, breach_hours))
	if percent is None or limit is None or hours is None or not 0 < percent < 100 or limit <= 0 or hours <= 0:
		raise _blocked(
			"WASTE_THRESHOLD_INVALID",
			_("Storage thresholds are not valid"),
			_("The warning must be between 1 and 99 %; the temperature and the hours must be above 0."),
			_("Correct the values, then save again."),
		)
	variance = _threshold_number(variance_percent) if variance_percent not in (None, "") else None
	if variance_percent not in (None, "") and (variance is None or variance <= 0):
		raise _blocked(
			"WASTE_THRESHOLD_INVALID",
			_("Storage thresholds are not valid"),
			_("The weight difference must be above 0."),
			_("Correct the values, then save again."),
		)
	doc = frappe.get_doc(SETTINGS)
	if variance is not None:
		doc.waste_variance_percent = variance
	doc.update(
		{"waste_warn_percent": int(percent), "waste_cold_limit_c": limit, "waste_cold_breach_hours": hours}
	)
	doc.flags.ignore_permissions = True
	doc.save()
	return thresholds()


# --- nhập kho, chuyển vị trí ------------------------------------------------------------------------------------------


def _location(name):
	row = (
		frappe.db.get_value(
			LOCATION,
			name,
			["name", "location_name", "is_cold", "is_active", "zone_station", "cold_breach_since"],
			as_dict=True,
		)
		if name
		else None
	)
	if not row or not cint(row.is_active):
		raise _blocked(
			"WASTE_LOCATION_INVALID",
			_("Storage location is not valid"),
			_("{0} is not an active waste storage location.").format(name or "-"),
			_("Scan a KE- code of the waste store, or ask R10 to set the location up."),
		)
	return row


def _right_locations(waste_type):
	parents = frappe.get_all(
		LOCATION_TYPE, filters={"waste_type": waste_type, "parenttype": LOCATION}, pluck="parent"
	)
	if not parents:
		return []
	return frappe.get_all(LOCATION, filters={"name": ["in", parents], "is_active": 1}, pluck="name")


def _check_type(waste_type, location):
	if frappe.db.exists(
		LOCATION_TYPE, {"parent": location, "parenttype": LOCATION, "waste_type": waste_type}
	):
		return
	right = _right_locations(waste_type)
	raise _blocked(
		"WASTE_WRONG_LOCATION",
		_("Wrong storage location"),
		_("Location {0} does not take {1}. Right location: {2}.").format(
			location, waste_type, ", ".join(right) or "-"
		),
		_("Take the bag to the right location and scan it there."),
	)


def _due_for(doc, room):
	"""Hạn lưu theo điều kiện lưu; trả (hạn, có tính lưu lạnh)."""
	hours = frappe.db.get_value(
		"Waste Type", doc.waste_type, ["max_storage_hours", "max_storage_cold_hours"], as_dict=True
	)
	cold = bool(
		cint(room.is_cold)
		and hours.max_storage_cold_hours
		and not room.cold_breach_since
		and not doc.cold_voided
	)
	return add_to_date(
		doc.collected_at, hours=hours.max_storage_cold_hours if cold else hours.max_storage_hours
	), cold


def _warn_at(collected_at, due, percent):
	start = get_datetime(collected_at)
	return start + (get_datetime(due) - start) * percent / 100


def _reset_alerts(doc, now):
	"""Hạn được nới thì cảnh báo cũ không còn đúng; NC đã tạo vẫn giữ."""
	if now < get_datetime(doc.storage_due):
		doc.overdue_at = None
	if now < _warn_at(doc.collected_at, doc.storage_due, thresholds()["warn_percent"]):
		doc.due_warned_at = None


def _put(doc, room, now):
	doc.storage_due, cold = _due_for(doc, room)
	doc.update(
		{
			"status": STORED,
			"storage_location": room.name,
			"stored_at": doc.stored_at or now,
			"cold_storage": int(cold),
		}
	)
	_reset_alerts(doc, now)
	doc.flags.ignore_permissions = True
	doc.save()
	return doc


def store(container, location):
	"""Quét túi + vị trí: nhập kho hoặc chuyển vị trí (FR-M10-03, .1, UC-35 A2, E1, E4)."""
	room = _location(location)
	if not container or not frappe.db.exists(CONTAINER, container):
		raise _blocked(
			"WASTE_CONTAINER_UNKNOWN",
			_("Waste bag not found"),
			_("Code {0} is not a collected waste bag.").format(container or "-"),
			_("Record a waste collection first (SCR-38)."),
		)
	doc = frappe.get_doc(CONTAINER, container, for_update=True)
	if doc.status not in (COLLECTED, STORED):
		raise _blocked(
			"WASTE_NOT_STORABLE",
			_("Waste bag cannot be stored"),
			_("Waste bag {0} is {1}.").format(doc.name, _(doc.status, context=CONTAINER)),
			_("Call R02 if the bag is on hold."),
		)
	_check_type(doc.waste_type, room.name)
	return _put(doc, room, now_datetime())


def _default_location(waste_type):
	parents = frappe.get_all(
		LOCATION_TYPE,
		filters={"waste_type": waste_type, "parenttype": LOCATION, "is_default": 1},
		pluck="parent",
	)
	active = (
		frappe.get_all(LOCATION, filters={"name": ["in", parents], "is_active": 1}, pluck="name")
		if parents
		else []
	)
	return active[0] if active else None


def store_collection(name):
	"""UC-35 A1: quét phiếu thu gom → mọi túi đang chờ vào vị trí mặc định của loại; thiếu vị trí thì không nhập túi nào."""
	bags = frappe.get_all(
		CONTAINER,
		filters={"collection": name, "status": COLLECTED},
		fields=["name", "waste_type"],
		order_by="name asc",
	)
	if not bags:
		raise _blocked(
			"WASTE_NOTHING_TO_STORE",
			_("Nothing to store"),
			_("Collection {0} has no bag waiting to be stored.").format(name or "-"),
			_("Check the collection code."),
		)
	defaults = {waste_type: _default_location(waste_type) for waste_type in {bag.waste_type for bag in bags}}
	missing = sorted(waste_type for waste_type, location in defaults.items() if not location)
	if missing:
		raise _blocked(
			"WASTE_NO_DEFAULT_LOCATION",
			_("No default location"),
			_("These waste types have no default storage location: {0}.").format(", ".join(missing)),
			_("Scan the location first and then each bag, or ask R10 to set a default location."),
		)
	now = now_datetime()
	for bag in bags:
		_put(frappe.get_doc(CONTAINER, bag.name, for_update=True), _location(defaults[bag.waste_type]), now)
	return {"stored": len(bags), "locations": sorted(set(defaults.values()))}


# --- nhiệt độ kho lạnh ------------------------------------------------------------------------------------------------


def record_temperature(location, temperature):
	"""R07 ghi nhiệt độ kho lạnh theo ca (UC-35 bước 4): một `Environment Log` của khu gắn với kho, nguồn Nhập tay."""
	room = _location(location)
	if not cint(room.is_cold):
		raise _blocked(
			"WASTE_NOT_COLD_ROOM",
			_("Not a cold room"),
			_("Location {0} is not a cold room.").format(room.name),
			_("Scan the location of the cold room."),
		)
	value = _threshold_number(temperature)
	if value is None:
		raise _blocked(
			"WASTE_TEMPERATURE_INVALID",
			_("Temperature is not valid"),
			_("The temperature must be a number."),
			_("Type the temperature read on the thermometer."),
		)
	doc = frappe.get_doc(
		{
			"doctype": "Environment Log",
			"zone": room.zone_station,
			"temperature": value,
			"measured_at": now_datetime(),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	check_cold_room(room, now_datetime())
	return doc


def _temperature(value):
	return _threshold_number(value) if cstr(value).strip() else None


def _breach_start(zone, limit):
	"""Giờ bắt đầu chuỗi lần đo liên tục vượt `limit` tính từ lần đo mới nhất; lần mới nhất không vượt → None."""
	start = None
	for row in frappe.get_all(
		"Environment Log",
		filters={"zone": zone, "docstatus": 1},
		fields=["temperature", "measured_at"],
		order_by="measured_at desc",
		limit=READING_WINDOW,
	):
		value = _temperature(row.temperature)
		if value is None:
			continue
		if value <= limit:
			break
		start = row.measured_at
	return start


def _void_cold(room, now):
	names = frappe.get_all(
		CONTAINER, filters={"storage_location": room.name, "status": STORED, "cold_storage": 1}, pluck="name"
	)
	for name in names:
		doc = frappe.get_doc(CONTAINER, name, for_update=True)
		doc.cold_voided = 1
		_put(doc, room, now)
	return names


def check_cold_room(room, now):
	"""FR-M10-03.2: quá thời lượng vượt ngưỡng → áp lại hạn lưu thường cho túi trong kho, báo một lần mỗi đợt."""
	limits = thresholds()
	start = _breach_start(room.zone_station, limits["cold_limit_c"])
	if start is None or now - get_datetime(start) < timedelta(hours=limits["breach_hours"]):
		if room.cold_breach_since and start is None:
			frappe.db.set_value(LOCATION, room.name, "cold_breach_since", None)
		return
	first_time = not room.cold_breach_since
	if first_time:
		frappe.db.set_value(LOCATION, room.name, "cold_breach_since", start)
		room.cold_breach_since = start
	names = _void_cold(room, now)
	if first_time:
		notification.emit(
			COLD_EVENT,
			frappe._dict(doctype=LOCATION, name=room.name),
			subject=_("Cold room {0} is above {1} °C").format(
				room.location_name, f"{limits['cold_limit_c']:g}"
			),
			message=_("Above the limit since {0}. {1} bags went back to the normal storage time.").format(
				get_datetime(start).strftime("%d/%m/%Y %H:%M"), len(names)
			),
			link=STOCK_LINK,
		)


def _check_cold_rooms(now):
	for name in frappe.get_all(LOCATION, filters={"is_cold": 1, "is_active": 1}, pluck="name"):
		check_cold_room(_location(name), now)


# --- hạn lưu ----------------------------------------------------------------------------------------------------------


def _open_filters():
	return {"status": ["in", [COLLECTED, STORED, HELD]], "storage_due": ["is", "set"]}


def _codes(rows):
	codes = [row.name for row in rows[:NOTICE_CODES]]
	if len(rows) > NOTICE_CODES:
		codes.append("...")
	return ", ".join(codes)


def _notify(event, rows, subject):
	notification.emit(
		event,
		frappe._dict(doctype=CONTAINER, name=rows[0].name),
		subject=subject,
		message=_codes(rows),
		link=STOCK_LINK,
	)


def _report_overdue(row):
	extension.run(
		NC_HOOK,
		{
			"kind": "overdue",
			"container": row.name,
			"waste_type": row.waste_type,
			"department": row.department,
			"due": row.storage_due,
		},
	)


def _check_due(now):
	percent = thresholds()["warn_percent"]
	warned, overdue = [], []
	for row in frappe.get_all(
		CONTAINER,
		filters=_open_filters(),
		fields=[
			"name",
			"waste_type",
			"department",
			"collected_at",
			"storage_due",
			"due_warned_at",
			"overdue_at",
		],
		order_by="storage_due asc",
	):
		if now >= get_datetime(row.storage_due):
			if not row.overdue_at:
				overdue.append(row)
		elif not row.due_warned_at and now >= _warn_at(row.collected_at, row.storage_due, percent):
			warned.append(row)
	for row in warned:
		frappe.db.set_value(CONTAINER, row.name, "due_warned_at", now, update_modified=False)
	for row in overdue:
		frappe.db.set_value(
			CONTAINER,
			row.name,
			{"overdue_at": now, "due_warned_at": row.due_warned_at or now},
			update_modified=False,
		)
		_report_overdue(row)
	if warned:
		_notify(DUE_EVENT, warned, _("{0} waste bags are close to the storage limit").format(len(warned)))
	if overdue:
		_notify(OVERDUE_EVENT, overdue, _("{0} waste bags are past the storage limit").format(len(overdue)))


def run_checks(now=None):
	"""Scheduler 15 phút: nhiệt độ kho lạnh trước vì có thể rút ngắn hạn lưu, rồi đến hạn lưu."""
	now = get_datetime(now) if now else now_datetime()
	_check_cold_rooms(now)
	_check_due(now)


# --- tồn kho ----------------------------------------------------------------------------------------------------------


def _state(row, now, percent):
	due = get_datetime(row.storage_due)
	if now >= due:
		return OVERDUE
	return DUE_SOON if now >= _warn_at(row.collected_at, due, percent) else OK


def _rank(state):
	return (OK, DUE_SOON, OVERDUE).index(state)


def _rooms():
	rooms = {
		row.name: row
		for row in frappe.get_all(
			LOCATION, fields=["name", "location_name", "is_cold", "zone_station", "cold_breach_since"]
		)
	}
	return rooms


def _last_reading(zone):
	rows = frappe.get_all(
		"Environment Log",
		filters={"zone": zone, "docstatus": 1, "temperature": ["is", "set"]},
		fields=["temperature", "measured_at"],
		order_by="measured_at desc",
		limit=1,
	)
	return rows[0] if rows else None


def stock(now=None):
	"""Tồn theo loại và vị trí, túi gấp nhất trước, nhiệt độ mới nhất của kho lạnh (SCR-39, FR-M10-03)."""
	now = get_datetime(now) if now else now_datetime()
	percent = thresholds()["warn_percent"]
	rooms = _rooms()
	containers, summary = [], {}
	for row in frappe.get_all(
		CONTAINER,
		filters={"status": ["in", [COLLECTED, STORED]]},
		fields=[
			"name",
			"waste_type",
			"weight_kg",
			"storage_location",
			"collected_at",
			"storage_due",
			"status",
		],
		order_by="storage_due asc, name asc",
	):
		state = _state(row, now, percent)
		remaining = int((get_datetime(row.storage_due) - now).total_seconds() // 60)
		room = rooms.get(row.storage_location)
		containers.append(
			{
				"name": row.name,
				"waste_type": row.waste_type,
				"weight_kg": row.weight_kg,
				"location": row.storage_location,
				"location_name": room.location_name if room else None,
				"status": row.status,
				"storage_due": row.storage_due,
				"remaining_minutes": remaining,
				"state": state,
			}
		)
		key = (row.waste_type, row.storage_location)
		group = summary.setdefault(
			key,
			{
				"waste_type": row.waste_type,
				"location": row.storage_location,
				"location_name": room.location_name if room else None,
				"bags": 0,
				"weight_kg": 0,
				"remaining_minutes": remaining,
				"state": state,
			},
		)
		group["bags"] += 1
		group["weight_kg"] = round(group["weight_kg"] + flt(row.weight_kg), 3)
		group["remaining_minutes"] = min(group["remaining_minutes"], remaining)
		if _rank(state) > _rank(group["state"]):
			group["state"] = state
	cold_rooms = []
	for room in rooms.values():
		if not cint(room.is_cold):
			continue
		reading = _last_reading(room.zone_station)
		cold_rooms.append(
			{
				"location": room.name,
				"location_name": room.location_name,
				"temperature": reading.temperature if reading else None,
				"measured_at": reading.measured_at if reading else None,
				"in_breach": bool(room.cold_breach_since),
			}
		)
	return {"summary": list(summary.values()), "containers": containers, "cold_rooms": cold_rooms}
