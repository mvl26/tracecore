"""RPC tracecore.v1.account.* — đặt PIN trạm từ form Employee trên Desk và đổi PIN tạm tại trạm (FR-M9-09, FR-M9-09.1,
UC-33 A3).

Quy tắc nằm ở `core.account` (`reset_pin_on_desk`, `change_station_pin`). Lỗi nghiệp vụ trả body ``ok: false`` (Audit Log
``Reject``), không ném.
"""

import frappe
from frappe import _

from tracecore.core import account, station_auth
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.v1._common import BadRequestError, reject_block


@frappe.whitelist(methods=["POST"])
def set_station_pin(employee, new_pin, supervisor_pin=None):
	"""Đặt PIN tạm 6 số cho `employee`; R02 kèm `supervisor_pin` là PIN trạm của chính mình. Nhân viên phải đổi PIN ở
	lần quẹt thẻ kế tiếp. Trả ``{"ok", "employee", "pin_change_required"}``."""
	try:
		account.reset_pin_on_desk(employee, new_pin, supervisor_pin)
	except BlockedError as error:
		return reject_block(error.block, "Employee", employee)
	return {"ok": True, "employee": employee, "pin_change_required": 1}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def change_pin(token=None, old_pin=None, new_pin=None, client_ts=None):
	"""Nhân viên đổi PIN của chính mình trên kiosk (modal bắt buộc sau quét thẻ khi PIN là PIN tạm).

	Phiên thẻ nhân viên (token trong body) xác định người đổi. Không dùng `@idempotent`, giống `v1.station.verify_pin`:
	Idempotency Key lưu băm SHA-256 của tham số, mà PIN 6 số dò ngược được (A7 không ghi PIN). Trả
	``{"ok": True, "pin_change_required": 0}``.
	"""
	timestamp = parse_client_ts(client_ts)
	if not isinstance(old_pin, str) or not isinstance(new_pin, str):
		raise BadRequestError(_("old_pin and new_pin must be strings."))
	employee = station = None
	try:
		with station_auth.as_session_user(token, client_ts=timestamp) as session:
			employee, station = session.employee, session.station
			account.change_station_pin(employee, old_pin, new_pin, station=station, client_ts=timestamp)
	except BlockedError as error:
		return reject_block(
			error.block, "Employee" if employee else None, employee, station=station, client_ts=timestamp
		)
	return {"ok": True, "pin_change_required": 0}
