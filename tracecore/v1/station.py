"""Station bearer-session RPCs and TC Agent/API-key station configuration."""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import error_codes, station_auth, zones
from tracecore.core import print as core_print
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.v1 import navigation
from tracecore.v1._common import (
	AGENT_ROLE,
	BadRequestError,
	require_agent_for,
	require_role,
	require_station,
	station_inactive_block,
)

PERIPHERAL_FIELDS = ["peripheral_type", "model", "connection", "host", "port", "serial_port", "baud_rate"]


def _with_station_role(session):
	"""Vai trò chính tại trạm cho dòng phiên (A-91, S-02)."""
	session["station_role"] = navigation.main_role(
		set(session.get("roles") or ()), zones.station_functions(session["station"])
	)
	department = frappe.db.get_value("Employee", session.get("employee"), "department")
	session["department"] = department
	session["department_name"] = (
		frappe.db.get_value("Department", department, "department_name") if department else None
	)
	return session


def _session_response(call, station=None, client_ts=None):
	try:
		return error_codes.attach_warnings(call())
	except BlockedError as error:
		if getattr(frappe.local, "request", None):
			frappe.local.response["http_status_code"] = error.block.http_status
		error_codes.log_block(error.block, station, client_ts)
		return {"ok": False, "error": error.block.as_dict()}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login(card_id=None, station=None, client_ts=None):
	# Do not persist bearer tokens in Idempotency Key responses; each login replaces the old session.
	timestamp = parse_client_ts(client_ts)
	if not isinstance(card_id, str) or not isinstance(station, str):
		raise BadRequestError(_("card_id and station must be strings."))
	return _session_response(
		lambda: {"ok": True, "session": _with_station_role(station_auth.login(card_id, station, timestamp))},
		station,
		timestamp,
	)


@frappe.whitelist(methods=["POST"])
def switch_station(token=None, station=None, client_ts=None):
	"""Đã quét thẻ thì chuyển sang trạm cùng khu không cần quét lại (A-90); tài khoản Desk phải có role của trạm đó.

	Khác khu thì trả khối `STATION_ZONE_RESCAN` trước khi xét role: máy trạm về màn quét thẻ của trạm đích.
	"""
	timestamp = parse_client_ts(client_ts)
	if not isinstance(station, str):
		raise BadRequestError(_("station must be a string."))

	def call():
		station_auth.require_same_zone(token, station, timestamp)
		if not navigation.can_open_station(station):
			raise frappe.PermissionError(_("This account cannot open station {0}.").format(station))
		return {
			"ok": True,
			"session": _with_station_role(station_auth.switch_station(token, station, timestamp)),
		}

	return _session_response(call, station, timestamp)


def _visible_stations(session):
	"""Trạm trên hàng nút sau khi quét thẻ (A-91): theo thẻ, không theo tài khoản Desk.

	KTV: cùng khu và có năng lực. Thẻ quản lý: đủ trạm. Trạm cùng khu tài khoản Desk không mở được thì không hiện vì bấm sẽ 403.
	"""
	roles = set(frappe.get_roles(session.user))
	overview = bool(roles & navigation.OVERVIEW_ROLES) or "System Manager" in roles
	rows = frappe.get_all(
		"Zone Station",
		filters={"is_zone": 0, "is_active": 1},
		fields=["name", "zone_station_name", "station_no", "parent_zone"],
	)
	rows.sort(key=lambda row: (not cint(row.station_no), cint(row.station_no), row.name))
	own_zone = next((row.parent_zone for row in rows if row.name == session.station), None)
	visible = []
	for row in rows:
		if not zones.station_screen_tabs(zones.station_functions(row.name)):
			continue
		same_zone = bool(own_zone) and row.parent_zone == own_zone
		show = row.name == session.station or overview
		if same_zone and not show:
			show = station_auth.can_work_at(session.employee, row.name)
		if same_zone and row.name != session.station:
			show = show and navigation.can_open_station(row.name)
		if show:
			visible.append(
				{"name": row.name, "label": row.zone_station_name, "station_no": cint(row.station_no)}
			)
	return visible


@frappe.whitelist(methods=["POST"])
def stations(token=None):
	"""Danh sách trạm cho hàng nút trên màn trạm (A-91, #1831); chỉ đọc, không tính là hoạt động."""

	def call():
		return {"ok": True, "stations": _visible_stations(station_auth.authenticate_session(token))}

	return _session_response(call)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def logout(token=None, client_ts=None):
	timestamp = parse_client_ts(client_ts)

	def call():
		station_auth.logout(token, timestamp)
		return {"ok": True}

	return _session_response(call)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def heartbeat(token=None, client_ts=None, recheck=None):
	"""`recheck`: máy trạm gửi 1 khi khôi phục phiên sau khi tải lại trang hoặc đổi trạm (A-90)."""
	timestamp = parse_client_ts(client_ts)

	def call():
		doc = station_auth.heartbeat(token, timestamp, recheck=bool(cint(recheck)))
		employee = frappe.db.get_value(
			"Employee", doc.employee, ["employee_name", "tc_pin_reset_required"], as_dict=True
		)
		return _with_station_role(
			{
				"ok": True,
				"session": doc.name,
				"employee": doc.employee,
				"employee_name": employee.employee_name,
				"roles": sorted(role for role in frappe.get_roles(doc.user) if role.startswith("TC R")),
				"station": doc.station,
				"expires_at": doc.absolute_expires_at,
				# khôi phục phiên sau khi tải lại trang vẫn phải mở lại modal đổi PIN tạm
				"pin_change_required": cint(employee.tc_pin_reset_required),
			}
		)

	return _session_response(call)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def verify_pin(token=None, pin=None, client_ts=None):
	timestamp = parse_client_ts(client_ts)

	def call():
		if not isinstance(token, str) or not token:
			station_auth.authenticate_session(token)  # stable SESSION_INVALID, before PIN validation
		if not isinstance(pin, str):
			raise BadRequestError(_("pin must be a string."))
		return {"ok": True, **station_auth.create_pin_proof(token, pin, timestamp)}

	return _session_response(call)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def verify_approver(token=None, card_id=None, pin=None, role="TC R02", client_ts=None):
	"""Người duyệt quét thẻ + nhập PIN trên kiosk đang mở phiên `token` (vd R02 duyệt vượt cơ số ở T7, architecture C6).

	Trả proof dùng một lần gắn với phiên này; RPC nghiệp vụ nhận proof và gọi `station_auth.consume_approver_proof`.
	"""
	timestamp = parse_client_ts(client_ts)

	def call():
		if not isinstance(token, str) or not token:
			station_auth.authenticate_session(token)  # SESSION_INVALID ổn định, trước khi kiểm thẻ/PIN
		if not all(isinstance(value, str) for value in (card_id, pin, role)):
			raise BadRequestError(_("card_id, pin and role must be strings."))
		return {"ok": True, **station_auth.create_approver_proof(token, card_id, pin, role, timestamp)}

	return _session_response(call)


def _station_row(station):
	row = frappe.db.get_value(
		"Zone Station",
		station,
		["name", "zone_station_name", "parent_zone", "zone_type", "station_no", "is_active"],
		as_dict=True,
	)
	functions = zones.station_functions(row.name)
	return {
		"name": row.name,
		"label": _(row.zone_station_name),
		"zone": row.parent_zone,
		"zone_type": row.zone_type,
		"zone_color": zones.zone_color_class(row.zone_type),
		"functions": functions,
		"station_no": cint(row.station_no),
		"screens": zones.station_screen_tabs(functions),
		"gate_labels": zones.gate_labels(),
		"gate_stations": zones.gate_stations(),
		"is_active": cint(row.is_active),
	}


def _active_peripherals(station):
	return frappe.get_all(
		"Station Peripheral",
		filters={"parent": station, "parenttype": "Zone Station", "is_active": 1},
		fields=PERIPHERAL_FIELDS,
		order_by="idx",
	)


@frappe.whitelist(methods=["POST"])
def config(station, client_ts=None):
	"""Cấu hình trạm cho agent: thông tin trạm, máy in hoạt động (D11) và thiết bị ngoại vi hoạt động (FEAT-002).

	Agent chỉ in tới máy in có trong danh sách này. Trạm không hoạt động → body từ chối STATION_INACTIVE (409).
	Không dùng @idempotent: chỉ đọc, giống `agent.heartbeat`.
	"""
	require_role(AGENT_ROLE)
	require_station(station, allow_inactive=True)
	require_agent_for(station)
	info = _station_row(station)
	if not info["is_active"]:
		block = station_inactive_block(station)
		if getattr(frappe.local, "request", None):
			frappe.local.response["http_status_code"] = block.http_status
		return {"ok": False, "error": block.as_dict()}
	return {
		"station": info,
		"printers": core_print.station_printers(station),
		"peripherals": _active_peripherals(station),
	}
