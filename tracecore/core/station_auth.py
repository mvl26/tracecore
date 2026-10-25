"""Xác thực thẻ/PIN và vòng đời phiên trạm (FEAT-003)."""

from __future__ import annotations

import hashlib
import re
import secrets
from contextlib import contextmanager
from copy import deepcopy

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime
from frappe.utils.password import get_decrypted_password, set_encrypted_password
from passlib.hash import bcrypt

from tracecore.core import audit
from tracecore.core.errors import Block, BlockedError

SESSION_HOURS = 8
IDLE_MINUTES = 10
PIN_LOCK_SECONDS = 300
PIN_FAILURE_LIMIT = 3
PROOF_SECONDS = 120
LOGIN_FAILURE_LIMIT = 30
LOGIN_WINDOW_SECONDS = 300
PIN_PATTERN = re.compile(r"^\d{6}$")


def normalize_card_id(card_id: str) -> str:
	return (card_id or "").strip().upper()


def _token_hash(token: str) -> str:
	return hashlib.sha256(token.encode()).hexdigest()


def _block(code: str, title: str, reason: str, action: str) -> BlockedError:
	return BlockedError(Block(code, _(title), _(reason), _(action)))


def _audit(action: str, employee=None, station=None, code=None, session=None, client_ts=None):
	audit.log(
		"Reject" if "Reject" in action else "Login",
		ref_doctype="Employee" if employee else "Station Session",
		ref_name=employee or session,
		new={"event": action, "station": station, "code": code, "session": session},
		station=station,
		client_ts=client_ts,
	)


def set_pin(employee: str, pin: str) -> None:
	if not PIN_PATTERN.fullmatch(pin or ""):
		raise _block(
			"PIN_FORMAT_INVALID",
			"PIN is invalid",
			"PIN must contain exactly 6 digits.",
			"Enter a 6-digit PIN.",
		)
	set_encrypted_password("Employee", employee, bcrypt.hash(pin), "tc_pin_hash")
	clear_pin_rate_limit(employee)


def _pin_key(employee: str, suffix: str) -> str:
	return f"tracecore:pin:{employee}:{suffix}"


def clear_pin_rate_limit(employee: str) -> None:
	frappe.cache.delete_value(_pin_key(employee, "failures"))
	frappe.cache.delete_value(_pin_key(employee, "locked"))


def verify_pin(employee: str, pin: str, client_ts=None) -> bool:
	cache = frappe.cache
	if cache.get_value(_pin_key(employee, "locked"), expires=True):
		raise _block(
			"PIN_LOCKED",
			"PIN is temporarily locked",
			"PIN was entered incorrectly 3 times.",
			"Wait 5 minutes and try again.",
		)
	stored = get_decrypted_password("Employee", employee, "tc_pin_hash", raise_exception=False)
	valid = bool(PIN_PATTERN.fullmatch(pin or "") and stored and bcrypt.verify(pin, stored))
	if valid:
		clear_pin_rate_limit(employee)
		_audit("PIN Verify", employee=employee, code="PIN_OK", client_ts=client_ts)
		return True
	# Atomic INCR: parallel guesses cannot each read the same stale count and exceed the limit.
	failures_key = cache.make_key(_pin_key(employee, "failures"))
	with cache.pipeline(transaction=True) as pipeline:
		pipeline.incr(failures_key)
		pipeline.expire(failures_key, PIN_LOCK_SECONDS)
		failures = int(pipeline.execute()[0])
	if failures >= PIN_FAILURE_LIMIT:
		cache.delete_value(_pin_key(employee, "failures"))
		cache.set_value(_pin_key(employee, "locked"), 1, expires_in_sec=PIN_LOCK_SECONDS)
		_audit("PIN Reject", employee=employee, code="PIN_LOCKED", client_ts=client_ts)
		raise _block(
			"PIN_LOCKED",
			"PIN is temporarily locked",
			"PIN was entered incorrectly 3 times.",
			"Wait 5 minutes and try again.",
		)
	_audit("PIN Reject", employee=employee, code="PIN_INVALID", client_ts=client_ts)
	raise _block("PIN_INVALID", "PIN is incorrect", "The PIN did not match.", "Check the PIN and try again.")


def lock_employee(employee):
	"""Serialize login, revocation and session use on the same authoritative row."""
	rows = frappe.db.sql(
		"select name, user_id, employee_name, status, tc_card_id, tc_card_enabled, tc_pin_reset_required from `tabEmployee` where name=%s for update",
		employee,
		as_dict=True,
	)
	return rows[0] if rows else None


def _employee_is_active(employee, user=None):
	return bool(
		employee
		and employee.status == "Active"
		and employee.tc_card_enabled
		and employee.user_id
		and (not user or employee.user_id == user)
		and frappe.db.get_value("User", employee.user_id, "enabled")
	)


def _card_rejected() -> BlockedError:
	# One public answer for unknown, disabled and unqualified cards: scanning cannot probe which exist.
	return _block(
		"CARD_INVALID",
		"Card login was rejected",
		"The card is invalid, inactive or not authorised for this station.",
		"Use an active employee card, or ask R02 to check your station competency.",
	)


def _throttle_key() -> str:
	return frappe.cache.make_key(
		"tracecore:login-reject:" + (getattr(frappe.local, "request_ip", None) or "local")
	)


def clear_login_throttle() -> None:
	frappe.cache.delete(_throttle_key())


def _check_login_throttle(client_ts=None) -> None:
	if int(frappe.cache.get(_throttle_key()) or 0) >= LOGIN_FAILURE_LIMIT:
		_audit("Login Reject", code="LOGIN_THROTTLED", client_ts=client_ts)
		raise _block(
			"LOGIN_THROTTLED",
			"Too many card attempts",
			"Too many rejected card scans from this device.",
			"Wait 5 minutes and try again.",
		)


def _count_login_failure() -> None:
	key = _throttle_key()
	with frappe.cache.pipeline(transaction=True) as pipeline:
		pipeline.incr(key)
		pipeline.expire(key, LOGIN_WINDOW_SECONDS)
		pipeline.execute()


def _active_employee(card_id: str, client_ts=None):
	card_id = normalize_card_id(card_id)
	name = frappe.db.get_value("Employee", {"tc_card_id": card_id}, "name")
	employee = lock_employee(name) if name else None
	# The locking read above sees revocations committed while waiting for the lock.
	if not _employee_is_active(employee) or employee.tc_card_id != card_id:
		_audit("Login Reject", code="CARD_INVALID", client_ts=client_ts)
		raise _card_rejected()
	return employee


def _require_station(station: str) -> None:
	row = frappe.db.get_value("Zone Station", station, ["is_zone", "is_active"], as_dict=True)
	if not row or row.is_zone or not row.is_active:
		raise _block(
			"STATION_INACTIVE",
			"Station is unavailable",
			"The station is missing or inactive.",
			"Choose an active station or contact R10.",
		)


def _require_competency(employee: str, station: str, client_ts=None) -> None:
	now = now_datetime()
	name = frappe.db.get_value(
		"Station Competency",
		{
			"employee": employee,
			"station": station,
			"is_active": 1,
			"valid_from": ["<=", now],
			"valid_until": [">=", now],
		},
		"name",
	)
	if not name:
		_audit(
			"Login Reject",
			employee=employee,
			station=station,
			code="COMPETENCY_REQUIRED",
			client_ts=client_ts,
		)
		raise _card_rejected()


def _close_session(doc, reason: str, client_ts=None) -> None:
	if not doc.is_open:
		return
	doc.is_open = 0
	doc.ended_at = now_datetime()
	doc.end_reason = reason
	doc.save(ignore_permissions=True)
	_audit(
		"Logout",
		employee=doc.employee,
		station=doc.station,
		code=reason,
		session=doc.name,
		client_ts=client_ts,
	)


def close_employee_sessions(employee: str, reason: str = "Employee Disabled", client_ts=None) -> int:
	lock_employee(employee)
	# Use a current read: a transaction may have started a snapshot before it
	# waited for a concurrent login to release the Employee row.
	names = frappe.db.sql(
		"select name from `tabStation Session` where employee=%s and is_open=1 for update",
		employee,
		pluck=True,
	)
	for name in names:
		_close_session(frappe.get_doc("Station Session", name, for_update=True), reason, client_ts)
	return len(names)


def login(card_id: str, station: str, client_ts=None) -> dict:
	_check_login_throttle(client_ts)
	try:
		return _login(card_id, station, client_ts)
	except BlockedError as error:
		if error.block.code == "CARD_INVALID":
			_count_login_failure()
		raise


def _login(card_id: str, station: str, client_ts=None) -> dict:
	_require_station(station)
	employee = _active_employee(card_id, client_ts)
	_require_competency(employee.name, station, client_ts)
	frappe.db.sql(
		"select name from `tabStation Session` where employee=%s and is_open=1 for update", employee.name
	)
	close_employee_sessions(employee.name, "Replaced", client_ts)
	token = secrets.token_urlsafe(32)
	started = now_datetime()
	doc = frappe.get_doc(
		{
			"doctype": "Station Session",
			"employee": employee.name,
			"user": employee.user_id,
			"station": station,
			"token_hash": _token_hash(token),
			"started_at": started,
			"last_activity_at": started,
			"absolute_expires_at": add_to_date(started, hours=SESSION_HOURS),
		}
	).insert(ignore_permissions=True)
	_audit(
		"Login",
		employee=employee.name,
		station=station,
		code="LOGIN_OK",
		session=doc.name,
		client_ts=client_ts,
	)
	return {
		"session": doc.name,
		"token": token,
		"employee": employee.name,
		"employee_name": employee.employee_name,
		"user": employee.user_id,
		"station": station,
		"expires_at": doc.absolute_expires_at,
		"roles": sorted(role for role in frappe.get_roles(employee.user_id) if role.startswith("TC R")),
	}


def authenticate_session(token: str, touch: bool = False, client_ts=None):
	if not isinstance(token, str) or not token:
		raise _block(
			"SESSION_INVALID",
			"Station session is invalid",
			"The session token is missing or invalid.",
			"Scan your employee card again.",
		)
	row = frappe.db.get_value(
		"Station Session",
		{"token_hash": _token_hash(token), "is_open": 1},
		["name", "employee"],
		as_dict=True,
	)
	if not row:
		raise _block(
			"SESSION_INVALID",
			"Station session is invalid",
			"The session has ended or the token is invalid.",
			"Scan your employee card again.",
		)
	employee = lock_employee(row.employee)
	doc = frappe.get_doc("Station Session", row.name, for_update=True)
	if not doc.is_open or not _employee_is_active(employee, doc.user):
		_close_session(doc, "Employee Disabled", client_ts)
		raise _block(
			"SESSION_INVALID",
			"Station session is invalid",
			"The session has ended or the token is invalid.",
			"Scan your employee card again.",
		)
	now = now_datetime()
	if get_datetime(doc.absolute_expires_at) <= now:
		_close_session(doc, "Expired", client_ts)
		raise _block(
			"SESSION_EXPIRED",
			"Station session expired",
			"The 8-hour session has ended.",
			"Scan your employee card again.",
		)
	if get_datetime(doc.last_activity_at) <= add_to_date(now, minutes=-IDLE_MINUTES):
		_close_session(doc, "Idle", client_ts)
		raise _block(
			"SESSION_IDLE",
			"Station session was locked",
			"There was no activity for 10 minutes.",
			"Scan your employee card again.",
		)
	if touch:
		doc.last_activity_at = now
		doc.save(ignore_permissions=True)
	return doc


def heartbeat(token: str, client_ts=None):
	return authenticate_session(token, touch=True, client_ts=client_ts)


def logout(token: str, client_ts=None) -> None:
	doc = authenticate_session(token, client_ts=client_ts)
	_close_session(doc, "Logout", client_ts)


def _proof_key(proof):
	return "tracecore:station-pin-proof:" + _token_hash(proof)


def create_pin_proof(token: str, pin: str, client_ts=None) -> dict:
	"""Issue an opaque proof once; neither secrets nor proof values enter the database."""
	from tracecore.core.account import require_pin_changed

	with as_session_user(token, client_ts=client_ts) as doc:
		require_pin_changed(doc.employee)
		verify_pin(doc.employee, pin, client_ts=client_ts)
		proof = secrets.token_urlsafe(32)
		value = frappe.as_json({"session": doc.name, "employee": doc.employee, "user": doc.user})
		frappe.cache.set(frappe.cache.make_key(_proof_key(proof)), value, ex=PROOF_SECONDS)
		return {"proof": proof, "expires_in": PROOF_SECONDS}


def consume_pin_proof(token: str, proof: str):
	"""Atomically consume a proof bound to this current live session, employee and user."""
	return _consume_proof(authenticate_session(token), proof)


def consume_session_pin_proof(session: str, proof: str):
	"""Như `consume_pin_proof` cho phiên `session` (tên Station Session) mà RPC trạm đã xác thực bằng token.

	`station_session` (v1) không chuyển token xuống hàm RPC; nơi cần proof (FEAT-021 Q7) dùng tên phiên của request.
	"""
	exists = isinstance(session, str) and session and frappe.db.exists("Station Session", session)
	doc = frappe.get_doc("Station Session", session) if exists else None
	if not doc or not doc.is_open:
		raise _block(
			"PIN_PROOF_INVALID",
			"PIN proof is invalid",
			"The PIN proof expired or was already used.",
			"Verify your PIN again.",
		)
	return _consume_proof(doc, proof)


# --- Người duyệt quét thẻ + PIN trên kiosk của người khác (architecture C6, UC-12 A1) --------------------------------
APPROVER_ROLES = ("TC R02",)  # FEAT-032 sẽ thêm TC R01 khi duyệt ghi đè cơ số tại T4


def _approver_key(proof):
	return "tracecore:station-approver-proof:" + _token_hash(proof)


def _approver_not_allowed() -> BlockedError:
	return _block(
		"APPROVER_NOT_ALLOWED",
		"Approver is not allowed",
		"This employee is not authorised to approve this action.",
		"Ask an authorised supervisor to scan the card and enter the PIN.",
	)


def _proof_invalid() -> BlockedError:
	return _block(
		"PIN_PROOF_INVALID",
		"PIN proof is invalid",
		"The PIN proof expired or was already used.",
		"Verify your PIN again.",
	)


def create_approver_proof(token: str, card_id: str, pin: str, role: str = "TC R02", client_ts=None) -> dict:
	"""Người duyệt (`role`) quét thẻ + nhập PIN trên phiên `token` của người khác; trả proof dùng một lần.

	Proof gắn với phiên đang mở, người duyệt và role; chỉ giữ trong cache `PROOF_SECONDS` giây, không vào database.
	Người không có role duyệt bị chặn trước khi thử PIN để không đốt lượt PIN của họ.
	"""
	from tracecore.core.account import require_pin_changed

	doc = authenticate_session(token, touch=True, client_ts=client_ts)
	if role not in APPROVER_ROLES:
		raise _approver_not_allowed()
	approver = _active_employee(card_id, client_ts)
	if role not in frappe.get_roles(approver.user_id):
		_audit(
			"Approve Reject",
			employee=approver.name,
			station=doc.station,
			code="APPROVER_NOT_ALLOWED",
			session=doc.name,
			client_ts=client_ts,
		)
		raise _approver_not_allowed()
	require_pin_changed(approver.name)
	verify_pin(approver.name, pin, client_ts=client_ts)
	proof = secrets.token_urlsafe(32)
	value = frappe.as_json(
		{"session": doc.name, "employee": approver.name, "user": approver.user_id, "role": role}
	)
	frappe.cache.set(frappe.cache.make_key(_approver_key(proof)), value, ex=PROOF_SECONDS)
	return {"proof": proof, "expires_in": PROOF_SECONDS, "employee_name": approver.employee_name}


def consume_approver_proof(session: str, proof: str, role: str = "TC R02"):
	"""Dùng (một lần) proof của `create_approver_proof` cho phiên `session` và `role`; trả người duyệt.

	Trả ``{employee, user, employee_name}``. Phiên đã đóng, proof sai/hết hạn/đã dùng hoặc khác role → PIN_PROOF_INVALID;
	người duyệt bị khóa thẻ hoặc mất role từ lúc nhập PIN → APPROVER_NOT_ALLOWED.
	"""
	stored = None
	if isinstance(proof, str) and proof:
		with frappe.cache.pipeline(transaction=True) as pipeline:
			key = frappe.cache.make_key(_approver_key(proof))
			pipeline.get(key)
			pipeline.delete(key)
			stored = pipeline.execute()[0]
	row = frappe.parse_json(stored.decode()) if stored else None
	exists = isinstance(session, str) and session and frappe.db.exists("Station Session", session)
	is_open = exists and frappe.db.get_value("Station Session", session, "is_open")
	if not row or not is_open or (row.session, row.role) != (session, role):
		raise _proof_invalid()
	approver = lock_employee(row.employee)
	if not _employee_is_active(approver, row.user) or role not in frappe.get_roles(row.user):
		raise _approver_not_allowed()
	return frappe._dict(employee=approver.name, user=row.user, employee_name=approver.employee_name)


def _consume_proof(doc, proof):
	from tracecore.core.account import require_pin_changed

	require_pin_changed(doc.employee)
	stored = None
	if isinstance(proof, str) and proof:
		with frappe.cache.pipeline(transaction=True) as pipeline:
			key = frappe.cache.make_key(_proof_key(proof))
			pipeline.get(key)
			pipeline.delete(key)
			stored = pipeline.execute()[0]
	row = frappe.parse_json(stored.decode()) if stored else None
	if not row or (row.session, row.employee, row.user) != (doc.name, doc.employee, doc.user):
		raise _block(
			"PIN_PROOF_INVALID",
			"PIN proof is invalid",
			"The PIN proof expired or was already used.",
			"Verify your PIN again.",
		)
	return doc


@contextmanager
def as_session_user(token: str, touch: bool = True, client_ts=None):
	"""Run as the station actor without altering or persisting the caller's web session."""
	doc = authenticate_session(token, touch=touch, client_ts=client_ts)
	# set_user mutates session in place and replaces these user-scoped local caches.
	# Keep the actual Desk session object untouched for native after-request persistence.
	fields = (
		"session",
		"session_obj",
		"form_dict",
		"request",
		"cache",
		"role_permissions",
		"user_perms",
		"new_doc_templates",
		"jenv_restricted",
		"jenv_unrestricted",
	)
	missing = object()
	previous = {field: getattr(frappe.local, field, missing) for field in fields}
	try:
		frappe.local.session = deepcopy(previous["session"])
		frappe.set_user(doc.user)
		# Station identity has no native cookie session to update while impersonating.
		frappe.local.session_obj = None
		form = previous["form_dict"]
		frappe.local.form_dict = deepcopy(form) if form is not missing else frappe._dict()
		yield doc
	finally:
		for field, value in previous.items():
			if value is missing:
				if hasattr(frappe.local, field):
					delattr(frappe.local, field)
			else:
				setattr(frappe.local, field, value)
