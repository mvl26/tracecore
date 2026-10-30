"""Nhật ký môi trường khu (M9, FEAT-008; FR-M9-04, FR-M9-04.1, FR-M9-04.2; UC-33 bước 3, A1; A-55).

`validate_reading` kiểm một `Environment Log`: khu đang theo dõi, ít nhất một chỉ số, độ ẩm 0-100 %, giờ đo không ở
tương lai, rồi so ngưỡng của khu (`Zone Station`, ô trống = không kiểm). Ghi sổ lần đo vượt ngưỡng → `ENV_OUT_OF_RANGE`
cho R02. `remind_missing` (scheduler 15 phút) nhắc khu chưa có lần đo trong khung trước mỗi mốc giờ của
`TraceCore Settings`. `record` là đường của cảm biến (`tracecore.v1.env.log`).

Ngưỡng và số đo là ô Data (Float của Frappe luôn lưu 0 khi trống): `to_number` đọc số, nhận dấu phẩy thập phân.
"""

import math
from datetime import datetime, time

import frappe
from frappe import _
from frappe.utils import add_to_date, formatdate, get_datetime, getdate, now_datetime

from tracecore.core import notification
from tracecore.core.errors import Block, BlockedError
from tracecore.tracecore.doctype.tracecore_settings.tracecore_settings import parse_times

# (trường số đo, ngưỡng thấp, ngưỡng cao, nhãn, đơn vị)
METRICS = (
	("temperature", "temp_min", "temp_max", "Temperature", "°C"),
	("humidity", "humidity_min", "humidity_max", "Humidity", "%"),
	("pressure_diff", "pressure_min", "pressure_max", "Pressure Difference", "Pa"),
)
FUTURE_TOLERANCE_MIN = 5
OUT_OF_RANGE_EVENT = "ENV_OUT_OF_RANGE"
MISSING_EVENT = "ENV_LOG_MISSING"
SENSOR, MANUAL = "Sensor", "Manual"


def _invalid(reason):
	return BlockedError(
		Block(
			"ENV_READING_INVALID",
			_("Environment reading is not valid"),
			reason,
			_("Check the values and the time of the reading, then record it again."),
		)
	)


def to_number(value, label):
	"""Số từ ô nhập (``18,5`` hoặc ``18.5``); trống → None; không phải số → `ENV_READING_INVALID`."""
	if value is None or isinstance(value, bool):
		return None
	if isinstance(value, int | float):
		number = float(value)
	else:
		text = str(value).strip().replace(",", ".")
		if not text:
			return None
		try:
			number = float(text)
		except ValueError:
			raise _invalid(_("{0} must be a number: {1}").format(label, value)) from None
	if not math.isfinite(number):
		raise _invalid(_("{0} must be a number: {1}").format(label, value))
	return number


def _zone(name):
	row = (
		frappe.db.get_value(
			"Zone Station",
			name,
			["name", "zone_station_name", "is_zone", "env_monitored"]
			+ [m[1] for m in METRICS]
			+ [m[2] for m in METRICS],
			as_dict=True,
		)
		if name
		else None
	)
	if not row or not row.is_zone or not row.env_monitored:
		raise BlockedError(
			Block(
				"ENV_ZONE_NOT_MONITORED",
				_("Zone is not monitored"),
				_("{0} is not a zone with environment monitoring turned on.").format(name or "-"),
				_("Choose a monitored zone, or ask R10 to turn on Monitor Environment for the zone."),
			)
		)
	return row


def validate_reading(doc):
	"""Kiểm và chuẩn hóa một lần đo; đặt ngày, nguồn, người ghi, kết quả so ngưỡng."""
	zone = _zone(doc.zone)
	values = {}
	for field, _low, _high, label, _unit in METRICS:
		value = to_number(doc.get(field), _(label))
		doc.set(field, None if value is None else f"{value:g}")
		if value is not None:
			values[field] = value
	if not values:
		raise _invalid(_("Enter at least one of temperature, humidity or pressure difference."))
	if "humidity" in values and not 0 <= values["humidity"] <= 100:
		raise _invalid(_("Humidity must be between 0 and 100 %."))
	measured_at = get_datetime(doc.measured_at or now_datetime())
	if measured_at > add_to_date(now_datetime(), minutes=FUTURE_TOLERANCE_MIN):
		raise _invalid(_("The measuring time {0} is in the future.").format(measured_at))
	doc.measured_at = measured_at
	doc.log_date = getdate(measured_at)
	if doc.is_new():
		doc.source = SENSOR if doc.flags.tc_sensor else MANUAL
		doc.recorded_by = frappe.session.user
	if doc.source != SENSOR:
		doc.sensor_id = None
	breaches, details = [], []
	for field, low, high, label, unit in METRICS:
		if field not in values:
			continue
		value = values[field]
		lowest, highest = to_number(zone.get(low), label), to_number(zone.get(high), label)
		if lowest is not None and value < lowest:
			breaches.append(field)
			details.append(
				_("{0} {1} {2} is below the minimum {3}").format(_(label), f"{value:g}", unit, f"{lowest:g}")
			)
		elif highest is not None and value > highest:
			breaches.append(field)
			details.append(
				_("{0} {1} {2} is above the maximum {3}").format(_(label), f"{value:g}", unit, f"{highest:g}")
			)
	doc.out_of_range = int(bool(breaches))
	doc.breaches = ",".join(breaches) or None
	doc.breach_detail = "\n".join(details) or None


def _zone_title(zone):
	return frappe.db.get_value("Zone Station", zone, "zone_station_name") or zone


def alert_out_of_range(doc):
	"""Ghi sổ lần đo vượt ngưỡng → cảnh báo R02 (FR-M9-04.1); người nhận thêm do R10 cấu hình ở Notification Rule."""
	if not doc.out_of_range:
		return
	notification.emit(
		OUT_OF_RANGE_EVENT,
		doc,
		subject=_("Environment out of range in {0}").format(_zone_title(doc.zone)),
		message=doc.breach_detail,
	)


def record(zone, measured_at, temperature=None, humidity=None, pressure_diff=None, sensor_id=None, note=None):
	"""Ghi sổ một lần đo của cảm biến (A-55 Q1, D4); quyền kiểm ở RPC."""
	doc = frappe.get_doc(
		{
			"doctype": "Environment Log",
			"zone": zone,
			"measured_at": measured_at,
			"temperature": temperature,
			"humidity": humidity,
			"pressure_diff": pressure_diff,
			"sensor_id": sensor_id,
			"note": note,
		}
	)
	doc.flags.tc_sensor = True
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	return doc


# --- nhắc thiếu số liệu (FR-M9-04.2) ---------------------------------------------------------------------------


def _has_reading(zone, start, end):
	return bool(
		frappe.get_all(
			"Environment Log",
			filters=[
				["zone", "=", zone],
				["docstatus", "=", 1],
				["measured_at", ">=", start],
				["measured_at", "<", end],
			],
			limit=1,
		)
	)


def windows(day, times):
	"""Khung [mốc trước, mốc này) của ngày `day` cho từng mốc giờ; mốc đầu tính từ 00:00."""
	start = datetime.combine(getdate(day), time.min)
	for slot in times:
		end = datetime.combine(getdate(day), slot)
		yield start, end
		start = end


def reminder_times():
	return parse_times(frappe.db.get_single_value("TraceCore Settings", "env_reminder_times"))


def remind_missing(now=None):
	"""Scheduler 15 phút: với mỗi mốc giờ đã qua trong ngày, khu theo dõi chưa có lần đo đã ghi sổ trong khung của
	mốc → nhắc (`ENV_LOG_MISSING`, mặc định R02), mỗi khu, mốc và ngày một lần."""
	now = get_datetime(now) if now else now_datetime()
	times = reminder_times()
	if not times:
		return
	zones = frappe.get_all(
		"Zone Station", filters={"is_zone": 1, "env_monitored": 1}, fields=["name", "zone_station_name"]
	)
	for start, end in windows(now.date(), times):
		if end > now:
			break
		for zone in zones:
			if not _has_reading(zone.name, start, end):
				_remind(zone, start, end)


def _remind(zone, start, end):
	title = zone.zone_station_name or zone.name
	marker = _("No environment reading in {0} from {1} to {2} on {3}.").format(
		title, start.strftime("%H:%M"), end.strftime("%H:%M"), formatdate(start.date())
	)
	if frappe.db.exists(
		"Notification Delivery",
		{
			"event_code": MISSING_EVENT,
			"ref_doctype": "Zone Station",
			"ref_name": zone.name,
			"message": marker,
		},
	):
		return
	notification.emit(
		MISSING_EVENT,
		frappe._dict(doctype="Zone Station", name=zone.name),
		subject=_("Environment reading missing: {0}").format(title),
		message=marker,
		link="/app/environment-log/new",
	)
