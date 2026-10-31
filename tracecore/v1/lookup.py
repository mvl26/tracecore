"""RPC tracecore.v1.lookup.* (A-68): gợi ý thiết bị và bộ/gói để CHỌN TAY trên trạm khi máy quét hỏng.

Chỉ đọc, không `@idempotent`, phiên thẻ như mọi RPC kiosk. Danh sách chỉ là gợi ý: mã chọn xong được gửi qua đúng RPC quét của
bước (kèm `entry_mode="Manual"` và lý do), nên trình tự cổng, trạng thái, hạn dùng, thu hồi vẫn do server kiểm lại.
Tìm theo mã/tên và phân trang (`start`, `page_length`) ở server.
"""

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.equipment import pick as equipment_pick
from tracecore.reprocessing import pick_list
from tracecore.v1._common import (
	LINEN_ROLES,
	LOAD_ROLES,
	PACKING_ROLES,
	RECEIVE_ROLES,
	STORAGE_ROLES,
	USAGE_ROLES,
	WASH_LOAD_ROLES,
	BadRequestError,
	require_any_role,
	run_at_step,
	station_session,
)
from tracecore.v1.assembly import ASSEMBLY_ROLES

SUPERVISOR = "TC R02"
STEP_ROLES = {
	"T1": RECEIVE_ROLES,
	"T2": WASH_LOAD_ROLES,
	"T3": ASSEMBLY_ROLES,
	"T4": PACKING_ROLES,
	"T5": LOAD_ROLES,
	"T6": STORAGE_ROLES,
	"T7": STORAGE_ROLES,
	"T8": USAGE_ROLES,
	"LIN": LINEN_ROLES,
}
ALL_ROLES = tuple(dict.fromkeys(role for roles in STEP_ROLES.values() for role in roles))


def _step_of(station):
	return frappe.db.get_value("Zone Station", station, "station_step") if isinstance(station, str) else None


def _text(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	return value


def _wrong_step(step):
	return BlockedError(
		Block(
			"STATION_WRONG_STEP",
			_("Wrong station"),
			_("Station step {0} has no list to choose from.").format(step or "-"),
			_("Open this screen on a station that takes a code."),
		)
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ALL_ROLES)
def equipment(station, q=None, purpose=None, start=0, page_length=20, client_ts=None, token=None):
	"""Thiết bị đang `Ready` hợp loại máy của bước (T2 máy rửa, T5 máy tiệt khuẩn…); `purpose="daily_test"` cho test hằng ngày."""
	timestamp = parse_client_ts(client_ts)
	step = _step_of(station)
	require_any_role(SUPERVISOR, *STEP_ROLES.get(step, ()))
	q, purpose = _text(q, "q"), _text(purpose, "purpose")

	def call():
		types = equipment_pick.types_for(step, purpose)
		if not types:
			raise _wrong_step(step)
		return {"ok": True, **equipment_pick.suggest(types, q, start, page_length)}

	return run_at_step(step, station, timestamp, call)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ALL_ROLES)
def set_units(station, q=None, department=None, start=0, page_length=20, client_ts=None, token=None):
	"""Bộ/gói đang chờ ở trạm: T1 mọi bộ đủ điều kiện tiếp nhận (ưu tiên khoa `department`), T2-T8 bộ/gói đã xong bước trước."""
	timestamp = parse_client_ts(client_ts)
	step = _step_of(station)
	require_any_role(SUPERVISOR, *STEP_ROLES.get(step, ()))
	q, department = _text(q, "q"), _text(department, "department")

	def call():
		if step not in pick_list.STEPS:
			raise _wrong_step(step)
		return {"ok": True, **pick_list.suggest(step, q, department, start, page_length)}

	return run_at_step(step, station, timestamp, call)
