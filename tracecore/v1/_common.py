"""Tiện ích chung cho RPC tracecore.v1: lỗi nghiệp vụ và mã HTTP, kiểm role/trạm, giờ server.

Hai kiểu từ chối cùng tồn tại (D3): `rejection` của FEAT-001 trả 200 + ``ok: false`` và giữ nguyên; `reject_block`
của FEAT-018 trả ``ok: false`` kèm mã HTTP theo loại lỗi (404/409/422) và ghi Audit Log `Reject`.
"""

import functools
import inspect
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.auth import SAFE_HTTP_METHODS
from frappe.utils import cint, now_datetime
from frappe.utils.data import get_system_timezone

from tracecore.core import audit, gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError

AGENT_ROLE = "TC Agent"
# R04 là role của user kiosk T4; System Manager để R10 xử lý trên Desk
PACKING_ROLES = ("TC R04", "System Manager")
# R06 là role của user kiosk T6 kho vô khuẩn (FEAT-025)
STORAGE_ROLES = ("TC R06", "System Manager")
# FEAT-021 Q20: nạp lô rửa do R03 (actor chính UC-06), R05, R02; dỡ/nhập dữ liệu/kết luận thêm R04 (cửa ra máy hai cửa)
WASH_LOAD_ROLES = ("TC R03", "TC R05", "TC R02", "System Manager")
WASH_UNLOAD_ROLES = ("TC R03", "TC R04", "TC R05", "TC R02", "System Manager")
# FEAT-022 Q13: nạp mẻ tiệt khuẩn và nhập dữ liệu chu trình do R05 (actor chính UC-09), R02 (actor phụ)
LOAD_ROLES = ("TC R05", "TC R02", "System Manager")
# T5b dỡ mẻ và giải phóng (FEAT-023): R05 dỡ và ghi chỉ thị, R02 giải phóng (PIN), R01 giải phóng khẩn (lý do)
RELEASE_ROLES = ("TC R05", "TC R02", "TC R01", "System Manager")
# FEAT-019 (A-31): tiếp nhận T1 do R03 (actor chính UC-05); R02 cũng làm được và là người duy nhất tiếp nhận cưỡng bức
RECEIVE_ROLES = ("TC R03", "TC R02", "System Manager")
SESSION_FLAG = "tc_station_session"


def current_station_session():
	"""Station Session (tên, employee, user) của RPC trạm đang chạy trong `station_session`, hoặc None.

	Token không đi xuống hàm RPC; nơi cần phiên (người thao tác, PIN proof) đọc ở đây.
	"""
	name = frappe.flags.get(SESSION_FLAG)
	if not name:
		return None
	return frappe.db.get_value("Station Session", name, ["name", "employee", "user", "station"], as_dict=True)


def station_session(*roles, desk_roles=()):
	"""Authorize human kiosk RPCs before idempotency lookup and execute as the session actor.

	Machine endpoints keep their dedicated TC Agent/API-key checks. Explicit-printer
	Desk requests retain their own role guard; a Frappe login alone never authorizes a kiosk.
	"""

	def decorate(fn):
		signature = inspect.signature(fn)

		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			kwargs = signature.bind(*args, **kwargs).arguments
			token = kwargs.pop("token", None)
			if desk_roles and kwargs.get("printer"):
				require_any_role(*desk_roles)
				return fn(**kwargs)
			timestamp = parse_client_ts(kwargs.get("client_ts"))
			# A body token avoids Frappe's OAuth interpretation of Authorization: Bearer.
			from tracecore.core import station_auth

			try:
				with station_auth.as_session_user(token, client_ts=timestamp) as session:
					if kwargs.get("station") != session.station:
						raise BlockedError(
							Block(
								"SESSION_STATION_MISMATCH",
								_("Wrong station"),
								_("The session belongs to another station."),
								_("Use the station where you scanned your card."),
							)
						)
					require_any_role(*roles)
					kwargs["station"] = session.station
					previous = frappe.flags.get(SESSION_FLAG)
					frappe.flags[SESSION_FLAG] = session.name
					try:
						return fn(**kwargs)
					finally:
						frappe.flags[SESSION_FLAG] = previous
			except BlockedError as error:
				if getattr(frappe.local, "request", None):
					frappe.local.response["http_status_code"] = error.block.http_status
				return {"ok": False, "error": error.block.as_dict()}

		return wrapper

	return decorate


class BadRequestError(frappe.ValidationError):
	"""Tham số sai định dạng (D3: 400), khác từ chối nghiệp vụ `Block` (404/409/422)."""

	http_status_code = 400


class StationInactiveError(frappe.ValidationError):
	"""Trạm đã ngừng hoạt động (409): agent thấy lỗi rõ ràng thay vì 417/500."""

	http_status_code = 409


def station_inactive_block(station):
	"""Block STATION_INACTIVE (E2): trạm bị vô hiệu hoặc chưa gán khu; chỉ R10 bật lại được (UC-33)."""
	return Block(
		"STATION_INACTIVE",
		_("Station deactivated"),
		_("Station {0} is deactivated.").format(station),
		_("Call R10 to activate the station."),
	)


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


def require_station(station, allow_inactive=False):
	"""Trạm phải tồn tại (không phải khu) và đang hoạt động; trạm tắt → `StationInactiveError` (409).

	`allow_inactive` cho RPC muốn tự trả body từ chối (`station.config`) sau khi đã kiểm quyền.
	"""
	row = (
		frappe.db.get_value("Zone Station", {"name": station, "is_zone": 0}, "is_active", as_dict=True)
		if station
		else None
	)
	if not row:
		frappe.throw(_("Station {0} does not exist.").format(station))
	if not allow_inactive and not cint(row.is_active):
		raise StationInactiveError(station_inactive_block(station).reason)


def require_agent_for(station):
	"""Agent chỉ được thao tác cho trạm của mình (user agent-<trạm>@…); System Manager được mọi trạm."""
	from tracecore.setup.provision import agent_user_email

	require_role(AGENT_ROLE)
	if "System Manager" in frappe.get_roles():
		return
	if frappe.session.user != agent_user_email(station):
		raise frappe.PermissionError(_("This agent is not registered for station {0}.").format(station))


def require_step(station, step):
	"""Block nếu `station` không phải trạm đang hoạt động của bước `step`; đúng thì None.

	Thứ tự kiểm: tồn tại → `is_active` (STATION_INACTIVE) → bước (STATION_WRONG_STEP).
	`step=None` bỏ qua kiểm bước (đường Desk của R10: chỉ cần trạm tồn tại và đang hoạt động).
	"""
	row = None
	if isinstance(station, str) and station:
		row = frappe.db.get_value(
			"Zone Station", station, ["is_zone", "is_active", "station_step"], as_dict=True
		)
	if row and not cint(row.is_zone):
		if not cint(row.is_active):
			return station_inactive_block(station)
		if step is None or row.station_step == step:
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
	request = getattr(frappe.local, "request", None)
	if request:
		frappe.local.response["http_status_code"] = block.http_status
		# Frappe v15 `app.sync_database` chỉ commit request POST/PUT/PATCH/DELETE (UNSAFE_HTTP_METHODS); request GET
		# (RPC chỉ đọc: v1.instrument.get_image, giai_preview, form_context…) bị rollback khi kết thúc, trừ khi
		# `frappe.local.flags.commit`. Không đặt cờ thì dòng Audit Log `Reject` vừa ghi mất ở production (test gọi hàm
		# trực tiếp không thấy). RPC GET không ghi gì khác, nên commit ở đây chỉ giữ dòng Audit Log này.
		keep_writes_on_get()
	return {"ok": False, "error": block.as_dict()}


def keep_writes_on_get():
	"""Request GET đang chạy → bật `frappe.local.flags.commit` để dòng Audit Log vừa ghi không bị rollback.

	Frappe v15 chỉ commit request POST/PUT/PATCH/DELETE; RPC chỉ đọc mà vẫn ghi Audit (từ chối, xuất CSV) gọi hàm này.
	"""
	request = getattr(frappe.local, "request", None)
	if request and getattr(request, "method", None) in SAFE_HTTP_METHODS:
		frappe.local.flags.commit = True


def desk_printer(name):
	"""Printer đang hoạt động mà người dùng Desk chọn; không có/không hoạt động → 400 (tham số sai, chưa ghi gì).

	Dùng chung cho nhãn QR đối tượng (`v1.print.object_label`) và thẻ/nhãn khay Set ID (`v1.set_unit`).
	"""
	if not isinstance(name, str) or not name:
		raise BadRequestError(_("printer must be a printer name."))
	row = frappe.db.get_value(
		"Printer", name, ["name", "station", "language", "supports_unicode", "is_active"], as_dict=True
	)
	if not row or not cint(row.is_active):
		raise BadRequestError(_("Printer {0} does not exist or is not active.").format(name))
	return row


def _job_name(value):
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		return str(value) if value > 0 else None
	return value.strip() if isinstance(value, str) and value.strip() else None


def job_names(names, limit):
	"""Tên Print Job (list hoặc chuỗi JSON của list; tên là số tự tăng, nhận số hoặc chuỗi), 1..`limit`; sai → 400."""
	if isinstance(names, str):
		try:
			names = frappe.parse_json(names)
		except ValueError:
			names = None
	if (
		not isinstance(names, list)
		or not 0 < len(names) <= limit
		or not all(_job_name(name) for name in names)
	):
		raise BadRequestError(_("names must be a list of 1 to {0} print job names.").format(limit))
	return [_job_name(name) for name in names]


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
