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

from tracecore.core import audit, error_codes, gs1, zones
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError

AGENT_ROLE = "TC Agent"
# R04 là role của user kiosk T4; R02 theo ma trận phân quyền (A-105); System Manager để R10 xử lý trên Desk
PACKING_ROLES = ("TC R04", "TC R02", "System Manager")
# R06 là role của user kiosk T6 kho vô khuẩn (FEAT-025); R02 theo ma trận (A-105)
STORAGE_ROLES = ("TC R06", "TC R02", "System Manager")
# T8 quét sử dụng tại khoa (FEAT-027): nhân viên khoa R08; R02 theo ma trận (A-105)
USAGE_ROLES = ("TC R08", "TC R02", "System Manager")
# FEAT-021 Q20: nạp lô rửa do R03 (actor chính UC-06), R05, R02; dỡ/nhập dữ liệu/kết luận thêm R04 (cửa ra máy hai cửa)
WASH_LOAD_ROLES = ("TC R03", "TC R05", "TC R02", "System Manager")
WASH_UNLOAD_ROLES = ("TC R03", "TC R04", "TC R05", "TC R02", "System Manager")
# FEAT-022 Q13: nạp mẻ tiệt khuẩn và nhập dữ liệu chu trình do R05 (actor chính UC-09), R02 (actor phụ)
LOAD_ROLES = ("TC R05", "TC R02", "System Manager")
# T5b dỡ mẻ và giải phóng (FEAT-023): R05 dỡ và ghi chỉ thị, R02 giải phóng (PIN), R01 giải phóng khẩn (lý do)
RELEASE_ROLES = ("TC R05", "TC R02", "TC R01", "System Manager")
# A-102: KTV ghi Không đạt được, việc loại mẻ do giám sát CSSD hoặc trưởng khoa
REJECT_ROLES = ("TC R02", "TC R01", "System Manager")
# FEAT-019 (A-31): tiếp nhận T1 do R03 (actor chính UC-05); R02 cũng làm được và là người duy nhất tiếp nhận cưỡng bức
RECEIVE_ROLES = ("TC R03", "TC R02", "System Manager")
# FEAT-033 (A-49): trạm đồ vải do R07 (actor chính UC-16); R02 hỗ trợ
LINEN_ROLES = ("TC R07", "TC R02", "System Manager")
# FEAT-047 (A-60): trạm thu gom chất thải do R07 (actor chính UC-34); R02 hỗ trợ
WASTE_ROLES = ("TC R07", "TC R02", "System Manager")
SESSION_FLAG = "tc_station_session"


def current_station_session():
	"""Station Session (tên, employee, user) của RPC trạm đang chạy trong `station_session`, hoặc None.

	Token không đi xuống hàm RPC; nơi cần phiên (người thao tác, PIN proof) đọc ở đây.
	"""
	name = frappe.flags.get(SESSION_FLAG)
	if not name:
		return None
	return frappe.db.get_value("Station Session", name, ["name", "employee", "user", "station"], as_dict=True)


def station_session(*roles, desk_roles=(), offline=False):
	"""Authorize human kiosk RPCs before idempotency lookup and execute as the session actor.

	Machine endpoints keep their dedicated TC Agent/API-key checks. Explicit-printer
	Desk requests retain their own role guard; a Frappe login alone never authorizes a kiosk.
	`offline=True` (chỉ RPC xếp hàng offline của T1/T4/T8, A-40): nhận phát lại ``X-TC-Replay`` với phiên xét tại
	`client_ts`; RPC khác bỏ qua header này và luôn cần phiên đang sống.
	"""

	def decorate(fn):
		signature = inspect.signature(fn)
		endpoint = f"{fn.__module__}.{fn.__name__}"

		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			kwargs = signature.bind(*args, **kwargs).arguments
			token = kwargs.pop("token", None)
			if desk_roles and kwargs.get("printer"):
				require_any_role(*desk_roles)
				return fn(**kwargs)
			timestamp = parse_client_ts(kwargs.get("client_ts"))
			from tracecore.core import sync

			if offline and sync.is_replay():
				return _replay(fn, endpoint, roles, kwargs, token, timestamp)
			return _live(fn, roles, kwargs, token, timestamp)

		return wrapper

	return decorate


def _run_as_session(fn, roles, kwargs, session):
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


def _block_body(block, station=None, client_ts=None):
	if getattr(frappe.local, "request", None):
		frappe.local.response["http_status_code"] = block.http_status
	error_codes.log_block(block, station, client_ts)
	return {"ok": False, "error": block.as_dict()}


def _client_errors():
	"""Lỗi do dữ liệu của giao dịch phát lại (thành Sync Conflict); lỗi khác là lỗi server, kiosk thử lại sau."""
	from tracecore.core.client_time import ClientTimestampError
	from tracecore.core.idempotency import IdempotencyConflictError

	return (ClientTimestampError, BadRequestError, IdempotencyConflictError, frappe.DoesNotExistError)


def _replay(fn, endpoint, roles, kwargs, token, timestamp):
	"""Giao dịch offline phát lại (`X-TC-Replay`): phiên xét tại `client_ts`; từ chối nghiệp vụ, thiếu quyền hoặc dữ
	liệu sai → Sync Conflict (A-40 Q2), body lỗi mang ``sync_conflict`` để kiosk biết được xóa mục khỏi hàng đợi.

	Không ghi gì khi khóa idempotent sai dạng hoặc token không thuộc phiên nào (khách gửi rác, review I3).
	"""
	from tracecore.core import station_auth, sync
	from tracecore.core.idempotency import _UUID, KEY_HEADER, IdempotencyKeyError

	key = (frappe.get_request_header(KEY_HEADER) or "").strip()
	if not _UUID.fullmatch(key):
		raise IdempotencyKeyError(_("Missing or invalid X-Idempotency-Key header."))
	session = None
	try:
		with station_auth.as_replay_user(token, kwargs.get("station"), timestamp) as session:
			try:
				result = error_codes.attach_warnings(_run_as_session(fn, roles, kwargs, session))
			except BlockedError as error:
				result = _block_body(error.block, kwargs.get("station"), timestamp)
	except BlockedError as error:
		result = _block_body(error.block)
	except frappe.PermissionError:
		frappe.clear_last_message()
		result = _block_body(
			Block(
				"PERMISSION_DENIED",
				_("Not permitted"),
				_("The station user may not do this action."),
				_("The transaction goes to R02 as a sync conflict."),
			)
		)
	except _client_errors() as exc:
		# giờ trạm sai, tham số sai… khi phát lại cũng là xung đột (A-40 Q2); lỗi khác (417 chung, 5xx) ném để kiosk thử lại
		status = getattr(exc, "http_status_code", 400)
		frappe.clear_last_message()
		result = _block_body(
			Block(
				type(exc).__name__,
				_("Request rejected"),
				str(exc),
				_("The transaction goes to R02 as a sync conflict."),
			)
		)
		result["error"]["http_status"] = status
		frappe.local.response["http_status_code"] = status
	error = result.get("error") if isinstance(result, dict) and result.get("ok") is False else None
	owner = (
		{"station": session.station, "employee": session.employee, "user": session.user}
		if session
		else station_auth.session_owner(token)
	)
	if error and owner:
		error["sync_conflict"] = sync.record_conflict(
			endpoint=endpoint,
			key=key,
			client_ts=timestamp,
			args=kwargs,
			error=error,
			http_status=error.get("http_status") or frappe.local.response.get("http_status_code"),
			session=owner,
		)
	return result


def _live(fn, roles, kwargs, token, timestamp):
	# A body token avoids Frappe's OAuth interpretation of Authorization: Bearer.
	from tracecore.core import station_auth

	try:
		with station_auth.as_session_user(token, client_ts=timestamp) as session:
			try:
				return error_codes.attach_warnings(_run_as_session(fn, roles, kwargs, session))
			except BlockedError as error:
				return _block_body(error.block, kwargs.get("station"), timestamp)
	except BlockedError as error:
		return _block_body(error.block)


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
	"""Block nếu `station` không phải trạm đang hoạt động có chức năng `step`; đúng thì None.

	`step` là mã chức năng hoặc tuple mã (có một trong số đó là đạt; A-64). Thứ tự kiểm: tồn tại → `is_active`
	(STATION_INACTIVE) → chức năng (STATION_WRONG_STEP). `step=None` bỏ qua kiểm chức năng (đường Desk của R10: chỉ cần
	trạm tồn tại và đang hoạt động).
	"""
	functions = () if step is None else ((step,) if isinstance(step, str) else tuple(step))
	label = zones.function_label(functions[0]) if functions else ""
	row = None
	if isinstance(station, str) and station:
		row = frappe.db.get_value("Zone Station", station, ["is_zone", "is_active"], as_dict=True)
	if row and not cint(row.is_zone):
		if not cint(row.is_active):
			return station_inactive_block(station)
		if not functions or zones.station_has_function(station, *functions):
			return None
	return Block(
		"STATION_WRONG_STEP",
		_("Wrong station"),
		_("{0} is not a {1} station.").format(station, label)
		if row
		else _("Station {0} does not exist.").format(
			station if isinstance(station, str) and station else "-"
		),
		_("Open this screen on a {0} station.").format(label),
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
		entry_mode=frappe.flags.get(ENTRY_MODE_FLAG),
	)
	error_codes.log_block(block, station, client_ts)
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


ENTRY_MODES = ("Scan", "Manual")
ENTRY_MODE_FLAG = "tc_entry_mode"
MAX_MANUAL_REASON = 140


def entry_mode_of(entry_mode, manual_reason):
	"""Chuẩn hóa cách nhập (A-68): ``(None, None)`` nếu RPC không phải thao tác nhập mã; mode sai → 400.

	Chọn tay (``Manual``) cần lý do; thiếu lý do không ném lỗi ở đây mà để `run_at_step` từ chối `MANUAL_REASON_REQUIRED`.
	"""
	if entry_mode is None:
		return None, None
	if entry_mode not in ENTRY_MODES:
		raise BadRequestError(_("entry_mode must be Scan or Manual."))
	if entry_mode == "Scan":
		return "Scan", None
	if manual_reason is not None and not isinstance(manual_reason, str):
		raise BadRequestError(_("manual_reason must be a string."))
	return "Manual", (manual_reason or "").strip()[:MAX_MANUAL_REASON]


def run_at_step(
	step,
	station,
	client_ts,
	call,
	ref_doctype=None,
	ref_name=None,
	raw=None,
	entry_mode=None,
	manual_reason=None,
):
	"""Chạy `call()` cho một trạm của bước `step`; mọi từ chối nghiệp vụ thành body lỗi qua `reject_block`.

	Trạm sai bước, hoặc `call` ném `BlockedError`, thì trả body lỗi (không ném lại). Ném lại sẽ làm Frappe hoàn tác
	cả request và mất dòng Audit Log lẫn Idempotency Key. Domain function đã hoàn tác phần ghi dở của nó (savepoint)
	trước khi ném. Lỗi khác (PermissionError, ValidationError…) vẫn lan ra để Frappe trả 4xx/5xx tương ứng.
	`client_ts` là datetime UTC đã qua `parse_client_ts`.

	`entry_mode` / `manual_reason` (A-68): cách nhập mã của RPC quét. Chọn tay ghi một dòng Audit Log `Manual Entry`
	(kèm lý do) trước khi chạy `call`, rồi đi qua đúng `call` như khi quét: không có đường tắt.
	"""
	mode, reason = entry_mode_of(entry_mode, manual_reason)
	previous = frappe.flags.get(ENTRY_MODE_FLAG)
	frappe.flags[ENTRY_MODE_FLAG] = mode
	try:
		block = require_step(station, step)
		if block:
			raise BlockedError(block)
		if mode == "Manual":
			_log_manual_entry(reason, ref_doctype, ref_name, raw, station, client_ts)
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
	finally:
		frappe.flags[ENTRY_MODE_FLAG] = previous


def _log_manual_entry(reason, ref_doctype, ref_name, raw, station, client_ts):
	if not reason:
		raise BlockedError(
			Block(
				"MANUAL_REASON_REQUIRED",
				_("Reason required"),
				_("Choosing a code by hand needs a reason."),
				_("Choose a reason (scanner broken, label unreadable or other), then select again."),
			)
		)
	audit.log(
		"Manual Entry",
		ref_doctype,
		str(ref_name)[: gs1.MAX_SCAN_LENGTH] if ref_name else None,
		new={"raw": str(raw)[: gs1.MAX_SCAN_LENGTH]} if raw else None,
		reason=reason,
		station=station if isinstance(station, str) else None,
		client_ts=client_ts,
		entry_mode="Manual",
	)
