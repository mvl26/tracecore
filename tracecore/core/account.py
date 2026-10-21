"""Account policy, credential changes and reversible Employee offboarding (FEAT-003)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, date_diff, getdate, now_datetime, today
from frappe.utils.password import check_password, update_password

from tracecore.core import audit, station_auth

PASSWORD_MIN_LENGTH = 10
PASSWORD_EXPIRY_DAYS = 90
PROOF_SECONDS = 120
WEB_ROLES = frozenset(("TC R01", "TC R02", "TC R09", "TC R10"))


def require_r10():
	# Administrator is the framework bootstrap/recovery identity, never a business role.
	if frappe.session.user != "Administrator" and "TC R10" not in frappe.get_roles():
		frappe.throw(_("Only R10 can create or disable accounts."), frappe.PermissionError)


def validate_password(password):
	if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
		frappe.throw(_("Password must contain at least 10 characters."))


def password_is_expired(user):
	if user in frappe.STANDARD_USERS:
		return False
	row = frappe.db.get_value("User", user, ["last_password_reset_date", "creation"], as_dict=True)
	return (
		not row
		or date_diff(today(), row.last_password_reset_date or getdate(row.creation)) >= PASSWORD_EXPIRY_DAYS
	)


def on_login(login_manager):
	# Native password recovery authenticates before refreshing its reset date. This
	# local marker is set only after the old password / recovery key is validated.
	if getattr(frappe.local, "tc_password_update_user", None) == login_manager.user:
		return
	if password_is_expired(login_manager.user):
		frappe.throw(
			_("Password expired. Change your password before signing in."), frappe.AuthenticationError
		)


def validate_user(doc, method=None):
	before = doc.get_doc_before_save()
	if doc.is_new() or (before and cint(doc.enabled) != cint(before.enabled)):
		require_r10()
	if before and str(doc.last_password_reset_date) != str(before.last_password_reset_date):
		frappe.throw(
			_("Use account credential actions to change or reset a password."), frappe.PermissionError
		)
	if doc.get("new_password"):
		validate_password(doc.new_password)
		if not doc.is_new():
			frappe.throw(
				_("Use account credential actions to change or reset a password."), frappe.PermissionError
			)


def user_updated(doc, method=None):
	before = doc.get_doc_before_save()
	if before and before.enabled and not doc.enabled:
		for employee in frappe.get_all("Employee", filters={"user_id": doc.name}, pluck="name"):
			frappe.db.set_value("Employee", employee, "tc_card_enabled", 0)
			station_auth.close_employee_sessions(employee)
		audit.log("Update", "User", doc.name, new={"event": "Account Disabled"})
	elif method == "after_insert":
		audit.log("Create", "User", doc.name, new={"event": "Account Created"})


def validate_employee(doc, method=None):
	before = doc.get_doc_before_save()
	if before and (
		cint(doc.tc_pin_reset_required) != cint(before.tc_pin_reset_required)
		or doc.tc_pin_hash != before.tc_pin_hash
	):
		frappe.throw(_("Use account credential actions to change or reset a PIN."), frappe.PermissionError)
	doc.tc_card_id = station_auth.normalize_card_id(doc.tc_card_id)
	if doc.tc_card_id and frappe.db.exists(
		"Employee", {"tc_card_id": doc.tc_card_id, "name": ["!=", doc.name or ""]}
	):
		frappe.throw(_("Station card ID must be unique."))
	if doc.status == "Left":
		if doc.user_id and frappe.db.get_value("User", doc.user_id, "enabled"):
			require_r10()
		doc.tc_card_enabled = 0


def employee_updated(doc, method=None):
	if doc.status == "Left" or not doc.tc_card_enabled:
		station_auth.close_employee_sessions(doc.name)
	if doc.status == "Left" and doc.user_id:
		user = frappe.get_doc("User", doc.user_id)
		if user.enabled:
			user.enabled = 0
			user.save(ignore_permissions=True)
	before = doc.get_doc_before_save()
	if before and (doc.status != before.status or doc.tc_card_enabled != before.tc_card_enabled):
		audit.log(
			"Update",
			"Employee",
			doc.name,
			new={
				"event": "Employee Access Changed",
				"status": doc.status,
				"card_enabled": cint(doc.tc_card_enabled),
			},
		)


def _record_password(user, password, reset=False):
	validate_password(password)
	update_password(user, password, logout_all_sessions=True)
	frappe.db.set_value(
		"User",
		user,
		{"last_password_reset_date": "1900-01-01" if reset else today(), "reset_password_key": ""},
	)
	for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
		station_auth.close_employee_sessions(employee)
	audit.log("Update", "User", user, new={"event": "Password Reset" if reset else "Password Changed"})


@frappe.whitelist(methods=["POST"])
def change_password(old_password, new_password):
	if frappe.session.user in frappe.STANDARD_USERS:
		frappe.throw(_("Sign in with an employee account."), frappe.PermissionError)
	check_password(frappe.session.user, old_password)
	_record_password(frappe.session.user, new_password)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def update_web_password(new_password, logout_all_sessions=0, key=None, old_password=None):
	"""Enforce length on Frappe's recovery form without bypassing native key checks."""
	from frappe.core.doctype.user.user import _get_user_for_update_password
	from frappe.core.doctype.user.user import update_password as native_update_password

	validate_password(new_password)
	resolved = _get_user_for_update_password(key, old_password)
	if resolved.get("message"):
		frappe.local.response.http_status_code = 410
		return resolved.message
	if not resolved.get("user"):
		frappe.throw(_("Current password or a valid recovery key is required."), frappe.AuthenticationError)
	previous = getattr(frappe.local, "tc_password_update_user", None)
	frappe.local.tc_password_update_user = resolved.user
	try:
		result = native_update_password(
			new_password, logout_all_sessions=1, key=key, old_password=old_password
		)
	finally:
		frappe.local.tc_password_update_user = previous
	audit.log("Update", "User", resolved.user, new={"event": "Password Changed"})
	return result


def require_pin_changed(employee):
	if frappe.db.get_value("Employee", employee, "tc_pin_reset_required"):
		raise station_auth._block(
			"PIN_CHANGE_REQUIRED",
			"PIN change required",
			"A supervisor reset this PIN.",
			"Change your PIN before continuing.",
		)


@frappe.whitelist(methods=["POST"])
def change_pin(token, old_pin, new_pin):
	with station_auth.as_session_user(token) as session:
		station_auth.verify_pin(session.employee, old_pin)
		if old_pin == new_pin:
			frappe.throw(_("Choose a different PIN."))
		station_auth.set_pin(session.employee, new_pin)
		frappe.db.set_value("Employee", session.employee, "tc_pin_reset_required", 0)
		audit.log(
			"Update", "Employee", session.employee, new={"event": "PIN Changed"}, station=session.station
		)


def _proof_key(proof):
	return "tracecore:account-proof:" + hashlib.sha256(proof.encode()).hexdigest()


@frappe.whitelist(methods=["POST"])
def issue_reset_proof(token, pin):
	session = station_auth.authenticate_session(token)
	if session.user != frappe.session.user or "TC R02" not in frappe.get_roles(session.user):
		frappe.throw(_("A supervisor station PIN proof is required."), frappe.PermissionError)
	employee = frappe.db.get_value("Employee", session.employee, ["status", "tc_card_enabled"], as_dict=True)
	if not employee or employee.status != "Active" or not employee.tc_card_enabled:
		frappe.throw(_("A supervisor station PIN proof is required."), frappe.PermissionError)
	require_pin_changed(session.employee)
	station_auth.verify_pin(session.employee, pin)
	proof = secrets.token_urlsafe(32)
	# No local Redis-wrapper cache: the transaction below consumes this exactly once.
	value = frappe.as_json({"user": session.user, "session": session.name})
	frappe.cache.set(frappe.cache.make_key(_proof_key(proof)), value, ex=PROOF_SECONDS)
	return proof


def _authorize_reset(proof):
	if frappe.session.user == "Administrator" or "TC R10" in frappe.get_roles():
		return
	if "TC R02" not in frappe.get_roles() or not isinstance(proof, str) or not proof:
		frappe.throw(_("A supervisor station PIN proof is required."), frappe.PermissionError)
	# MULTI/EXEC keeps read-and-delete atomic without requiring Redis 6.2 GETDEL.
	with frappe.cache.pipeline(transaction=True) as pipeline:
		key = frappe.cache.make_key(_proof_key(proof))
		pipeline.get(key)
		pipeline.delete(key)
		stored = pipeline.execute()[0]
	row = frappe.parse_json(stored.decode()) if stored else None
	if row and row.user == frappe.session.user:
		session = frappe.get_doc("Station Session", row.session)
		employee = frappe.db.get_value(
			"Employee", session.employee, ["status", "tc_card_enabled", "tc_pin_reset_required"], as_dict=True
		)
		if (
			session.is_open
			and session.user == frappe.session.user
			and employee
			and employee.status == "Active"
			and employee.tc_card_enabled
			and not employee.tc_pin_reset_required
			and frappe.db.get_value("User", session.user, "enabled")
			and session.absolute_expires_at > now_datetime()
			and session.last_activity_at > now_datetime() - timedelta(minutes=station_auth.IDLE_MINUTES)
		):
			return
	frappe.throw(_("A supervisor station PIN proof is required."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def reset_password(user, new_password, proof=None):
	validate_password(new_password)
	_authorize_reset(proof)
	if user in frappe.STANDARD_USERS or not frappe.db.exists("User", user):
		frappe.throw(_("Choose an employee account."))
	_record_password(user, new_password, reset=True)


@frappe.whitelist(methods=["POST"])
def reset_pin(employee, new_pin, proof=None):
	_authorize_reset(proof)
	station_auth.set_pin(employee, new_pin)
	frappe.db.set_value("Employee", employee, "tc_pin_reset_required", 1)
	audit.log("Update", "Employee", employee, new={"event": "PIN Reset"})
