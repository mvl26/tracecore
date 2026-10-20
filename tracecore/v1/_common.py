"""Tiện ích chung cho RPC tracecore.v1: lỗi nghiệp vụ và mã HTTP, kiểm role/trạm, giờ server.

Hai kiểu từ chối cùng tồn tại (D3): `rejection` của FEAT-001 trả 200 + ``ok: false`` và giữ nguyên; `reject_block`
của FEAT-018 trả ``ok: false`` kèm mã HTTP theo loại lỗi (404/409/422) và ghi Audit Log `Reject`.
"""

from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, now_datetime
from frappe.utils.data import get_system_timezone

from tracecore.core import audit, gs1
from tracecore.core.errors import Block, BlockedError

AGENT_ROLE = "TC Agent"
# R04 là role của user kiosk T4; System Manager để R10 xử lý trên Desk
PACKING_ROLES = ("TC R04", "System Manager")


class BadRequestError(frappe.ValidationError):
	"""Tham số sai định dạng (D3: 400), khác từ chối nghiệp vụ `Block` (404/409/422)."""

	http_status_code = 400


def rejection(code, title, reason, action):
	"""Lỗi nghiệp vụ cho trạm: kết quả → lý do → hành động (design.md §6)."""
	return {"ok": False, "error": {"code": code, "title": title, "reason": reason, "action": action}}


def server_time():
	"""Giờ server ISO 8601 có offset theo múi giờ hệ thống."""
	return now_datetime().replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat()


def require_role(role):
	# Không dùng frappe.only_for: hàm đó bỏ qua kiểm tra khi chạy test
	if role not in frappe.get_roles():
		raise frappe.PermissionError(_("This method requires the role {0}.").format(role))


def require_any_role(*roles):
	"""Người gọi phải có ít nhất một trong `roles`; không có → PermissionError (403), chưa ghi gì."""
	if not set(roles) & set(frappe.get_roles()):
		raise frappe.PermissionError(_("This method requires one of the roles {0}.").format(", ".join(roles)))


def require_station(station):
	if not station or not frappe.db.exists("Zone Station", {"name": station, "is_zone": 0}):
		frappe.throw(_("Station {0} does not exist.").format(station))


def require_agent_for(station):
	"""Agent chỉ được thao tác cho trạm của mình (user agent-<trạm>@…); System Manager được mọi trạm."""
	from tracecore.setup.provision import agent_user_email

	require_role(AGENT_ROLE)
	if "System Manager" in frappe.get_roles():
		return
	if frappe.session.user != agent_user_email(station):
		raise frappe.PermissionError(_("This agent is not registered for station {0}.").format(station))


def require_step(station, step):
	"""Block STATION_WRONG_STEP nếu `station` không phải trạm (không phải khu) của bước `step`; đúng thì None."""
	row = None
	if isinstance(station, str) and station:
		row = frappe.db.get_value("Zone Station", station, ["is_zone", "station_step"], as_dict=True)
	if row and not cint(row.is_zone) and row.station_step == step:
		return None
	return Block(
		"STATION_WRONG_STEP",
		_("Wrong station"),
		_("{0} is not a {1} station.").format(station, step)
		if row
		else _("Station {0} does not exist.").format(
			station if isinstance(station, str) and station else "-"
		),
		_("Open this screen on a {0} station.").format(step),
	)


def reject_block(block, ref_doctype=None, ref_name=None, raw=None, *, station=None, client_ts=None):
	"""Từ chối nghiệp vụ (FEAT-018): Audit Log `Reject` + mã HTTP theo loại lỗi + body ``ok: false``.

	`reason` của dòng Audit Log là mã lỗi; `new_value` mang chuỗi quét `raw` (cắt như FEAT-001) và các mục thiếu
	(`block.items`). Mã HTTP (``block.http_status``) chỉ đặt khi đang có request; `_common.rejection` của FEAT-001
	giữ nguyên (200). Hàm này KHÔNG ném lỗi: RPC phải trả body để dòng Audit Log và Idempotency Key được commit.
	"""
	new = {}
	if raw:
		new["raw"] = str(raw)[: gs1.MAX_SCAN_LENGTH]
	if block.items:
		new["items"] = block.items
	audit.log(
		"Reject",
		ref_doctype,
		str(ref_name)[: gs1.MAX_SCAN_LENGTH] if ref_name else None,
		new=new or None,
		reason=block.code,
		station=station,
		client_ts=client_ts,
	)
	if getattr(frappe.local, "request", None):
		frappe.local.response["http_status_code"] = block.http_status
	return {"ok": False, "error": block.as_dict()}


def run_at_step(step, station, client_ts, call, ref_doctype=None, ref_name=None, raw=None):
	"""Chạy `call()` cho một trạm của bước `step`; mọi từ chối nghiệp vụ thành body lỗi qua `reject_block`.

	Trạm sai bước, hoặc `call` ném `BlockedError`, thì trả body lỗi (không ném lại). Ném lại sẽ làm Frappe hoàn tác
	cả request và mất dòng Audit Log lẫn Idempotency Key. Domain function đã hoàn tác phần ghi dở của nó (savepoint)
	trước khi ném. Lỗi khác (PermissionError, ValidationError…) vẫn lan ra để Frappe trả 4xx/5xx tương ứng.
	`client_ts` là datetime UTC đã qua `parse_client_ts`.
	"""
	try:
		block = require_step(station, step)
		if block:
			raise BlockedError(block)
		return call()
	except BlockedError as error:
		return reject_block(
			error.block,
			ref_doctype,
			ref_name,
			raw,
			station=station if isinstance(station, str) else None,
			client_ts=client_ts,
		)
