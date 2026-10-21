"""Xác thực thẻ/PIN và vòng đời phiên trạm (FEAT-003)."""

from __future__ import annotations

import hashlib
import re
import secrets
from contextlib import contextmanager

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
PIN_PATTERN = re.compile(r"^\d{6}$")


def normalize_card_id(card_id: str) -> str:
	return (card_id or "").strip().upper()


def _token_hash(token: str) -> str:
	return hashlib.sha256(token.encode()).hexdigest()


def _block(code: str, title: str, reason: str, action: str) -> BlockedError:
	return BlockedError(Block(code, _(title), _(reason), _(action)))


def _audit(action: str, employee=None, station=None, code=None, session=None):
	audit.log(
		"Reject" if "Reject" in action else "Login",
		ref_doctype="Employee" if employee else "Station Session",
		ref_name=employee or session,
		new={"event": action, "station": station, "code": code, "session": session},
		station=station,
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


def verify_pin(employee: str, pin: str) -> bool:
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
		_audit("PIN Verify", employee=employee, code="PIN_OK")
		return True
	failures = int(cache.get_value(_pin_key(employee, "failures"), expires=True) or 0) + 1
	if failures >= PIN_FAILURE_LIMIT:
		cache.delete_value(_pin_key(employee, "failures"))
		cache.set_value(_pin_key(employee, "locked"), 1, expires_in_sec=PIN_LOCK_SECONDS)
		_audit("PIN Reject", employee=employee, code="PIN_LOCKED")
		raise _block(
			"PIN_LOCKED",
			"PIN is temporarily locked",
			"PIN was entered incorrectly 3 times.",
			"Wait 5 minutes and try again.",
		)
	cache.set_value(_pin_key(employee, "failures"), failures, expires_in_sec=PIN_LOCK_SECONDS)
	_audit("PIN Reject", employee=employee, code="PIN_INVALID")
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


def _active_employee(card_id: str):
	card_id = normalize_card_id(card_id)
	name = frappe.db.get_value("Employee", {"tc_card_id": card_id}, "name")
	employee = lock_employee(name) if name else None
	# The locking read above sees revocations committed while waiting for the lock.
	if not _employee_is_active(employee) or employee.tc_card_id != card_id:
		_audit("Login Reject", code="CARD_INVALID")
		raise _block(
			"CARD_INVALID",
			"Card login was rejected",
			"The card is invalid or inactive.",
			"Use an active employee card or contact a supervisor.",
		)
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


def _require_competency(employee: str, station: str) -> None:
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
		_audit("Login Reject", employee=employee, station=station, code="COMPETENCY_REQUIRED")
		raise _block(
			"COMPETENCY_REQUIRED",
			"Card login was rejected",
			"The employee has no valid competency for this station.",
			"Ask R02 to check competency or temporary access.",
		)


def _close_session(doc, reason: str) -> None:
	if not doc.is_open:
		return
	doc.is_open = 0
	doc.ended_at = now_datetime()
	doc.end_reason = reason
	doc.save(ignore_permissions=True)
	_audit("Logout", employee=doc.employee, station=doc.station, code=reason, session=doc.name)


def close_employee_sessions(employee: str, reason: str = "Employee Disabled") -> int:
	lock_employee(employee)
	# Use a current read: a transaction may have started a snapshot before it
	# waited for a concurrent login to release the Employee row.
	names = frappe.db.sql(
		"select name from `tabStation Session` where employee=%s and is_open=1 for update",
		employee,
		pluck=True,
	)
	for name in names:
		_close_session(frappe.get_doc("Station Session", name, for_update=True), reason)
	return len(names)


def login(card_id: str, station: str) -> dict:
	_require_station(station)
	employee = _active_employee(card_id)
	_require_competency(employee.name, station)
	frappe.db.sql(
		"select name from `tabStation Session` where employee=%s and is_open=1 for update", employee.name
	)
	close_employee_sessions(employee.name, "Replaced")
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
	_audit("Login", employee=employee.name, station=station, code="LOGIN_OK", session=doc.name)
	return {
		"session": doc.name,
		"token": token,
		"employee": employee.name,
		"employee_name": employee.employee_name,
		"user": employee.user_id,
		"station": station,
		"expires_at": doc.absolute_expires_at,
	}


def authenticate_session(token: str, touch: bool = False):
	if not token:
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
		_close_session(doc, "Employee Disabled")
		raise _block(
			"SESSION_INVALID",
			"Station session is invalid",
			"The session has ended or the token is invalid.",
			"Scan your employee card again.",
		)
	now = now_datetime()
	if get_datetime(doc.absolute_expires_at) <= now:
		_close_session(doc, "Expired")
		raise _block(
			"SESSION_EXPIRED",
			"Station session expired",
			"The 8-hour session has ended.",
			"Scan your employee card again.",
		)
	if get_datetime(doc.last_activity_at) <= add_to_date(now, minutes=-IDLE_MINUTES):
		_close_session(doc, "Idle")
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


def heartbeat(token: str):
	return authenticate_session(token, touch=True)


def logout(token: str) -> None:
	doc = authenticate_session(token)
	_close_session(doc, "Logout")


@contextmanager
def as_session_user(token: str, touch: bool = True):
	doc = authenticate_session(token, touch=touch)
	previous = frappe.session.user
	frappe.set_user(doc.user)
	try:
		yield doc
	finally:
		frappe.set_user(previous)
