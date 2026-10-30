"""RPC tracecore.v1.env.* — cảm biến môi trường đẩy số liệu qua Station Agent (FEAT-008, FR-M9-04, EI-HW-005, A-55).

Agent của trạm (role TC Agent, API key) gọi `log` cho khu của trạm (`parent_zone`); không có Modbus (A-55 Q1).
Thứ tự: quyền agent của trạm → trạm hoạt động → `@idempotent` → định dạng tham số (400) → dịch vụ. Từ chối nghiệp vụ
(`BlockedError`) thành ``{"ok": false, "error": {...}}`` kèm mã HTTP và Audit Log `Reject`.
"""

import frappe
from frappe import _

from tracecore.admin_reports import environment
from tracecore.core.client_time import parse_client_ts, to_system_time
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import BadRequestError, reject_block, require_agent_for, require_station

MAX_TEXT = 140


def _number(value, name):
	if value is None or value == "":
		return None
	if isinstance(value, bool) or not isinstance(value, int | float | str):
		raise BadRequestError(_("{0} must be a number.").format(name))
	if isinstance(value, str):
		try:
			float(value.strip().replace(",", "."))
		except ValueError:
			raise BadRequestError(_("{0} must be a number.").format(name)) from None
	return value


def _text(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	return (value or "").strip()[:MAX_TEXT] or None


@frappe.whitelist(methods=["POST"])
@idempotent
def log(
	station,
	measured_at,
	temperature=None,
	humidity=None,
	pressure_diff=None,
	sensor_id=None,
	note=None,
	client_ts=None,
):
	"""Ghi sổ một lần đo của cảm biến cho khu của trạm; trả ``{"ok", "name", "out_of_range"}``."""
	require_agent_for(station)  # trước require_station: agent không dò được trạm khác
	require_station(station)
	timestamp = parse_client_ts(client_ts)
	# giờ đo ISO 8601 có offset như client_ts → giờ hệ thống (Asia/Ho_Chi_Minh)
	measured = to_system_time(parse_client_ts(measured_at))
	values = {
		"temperature": _number(temperature, "temperature"),
		"humidity": _number(humidity, "humidity"),
		"pressure_diff": _number(pressure_diff, "pressure_diff"),
	}
	zone = frappe.db.get_value("Zone Station", station, "parent_zone")
	try:
		doc = environment.record(
			zone,
			measured,
			sensor_id=_text(sensor_id, "sensor_id"),
			note=_text(note, "note"),
			**values,
		)
	except BlockedError as error:
		return reject_block(error.block, "Environment Log", None, station=station, client_ts=timestamp)
	return {"ok": True, "name": doc.name, "out_of_range": doc.out_of_range}
