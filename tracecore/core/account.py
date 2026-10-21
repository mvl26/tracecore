"""Account policy, credential changes and reversible Employee offboarding (FEAT-003)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, date_diff, getdate, now_datetime, today
from frappe.utils.password import check_password, update_password

from tracecore.core import audit, station_auth
from tracecore.core.errors import BlockedError

PASSWORD_MIN_LENGTH = 10
PASSWORD_EXPIRY_DAYS = 90
WEB_ROLES = frozenset(("TC R01", "TC R02", "TC R09", "TC R10"))


def _has_role(role, user=None):
	# frappe.get_roles("Administrator") synthesizes every role. Business authority
	# must instead be explicitly assigned, including for the framework superuser.
	return bool(
		frappe.db.exists(
			"Has Role", {"parent": user or frappe.session.user, "parenttype": "User", "role": role}
		)
	)


def require_r10(install_creation=False):
	if install_creation and frappe.flags.in_install and frappe.session.user == "Administrator":
		return
	if not _has_role("TC R10"):
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
	if password_is_expired(login_manager.user):
		frappe.throw(
			_("Password expired. Change your password before signing in."), frappe.AuthenticationError
		)


def validate_user(doc, method=None):
	before = doc.get_doc_before_save()
	if doc.is_new():
		require_r10(install_creation=True)
	elif before and cint(doc.enabled) != cint(before.enabled):
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
	if before:
		station_auth.lock_employee(doc.name)
		if (doc.user_id or "") != (before.user_id or ""):
			require_r10()
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
		if doc.user_id or (before and before.user_id):
			require_r10()
		doc.tc_card_enabled = 0
	elif before and before.user_id and not doc.user_id:
		doc.tc_card_enabled = 0


def employee_updated(doc, method=None):
	before = doc.get_doc_before_save()
	link_changed = before and (doc.user_id or "") != (before.user_id or "")
	if doc.status == "Left" or not doc.tc_card_enabled or link_changed:
		station_auth.close_employee_sessions(doc.name)
	if doc.status == "Left":
		for user_id in {doc.user_id, before.user_id if before else None} - {None, ""}:
			user = frappe.get_doc("User", user_id)
			if user.enabled:
				user.enabled = 0
				user.save(ignore_permissions=True)
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
	"""Change credentials without creating a session; normal login still requires OTP."""
	from frappe.core.doctype.user.user import _get_user_for_update_password

	validate_password(new_password)
	if key:
		resolved = _get_user_for_update_password(key, None)
	elif old_password and frappe.session.user not in frappe.STANDARD_USERS:
		resolved = frappe._dict(user=check_password(frappe.session.user, old_password))
	else:
		resolved = frappe._dict()
	if resolved.get("message"):
		frappe.local.response.http_status_code = 410
		return resolved.message
	if (
		not resolved.get("user")
		or resolved.user in frappe.STANDARD_USERS
		or not frappe.db.get_value("User", resolved.user, "enabled")
	):
		frappe.throw(_("Current password or a valid recovery key is required."), frappe.AuthenticationError)
	_record_password(resolved.user, new_password)
	return "/login"


@frappe.whitelist(allow_guest=True, methods=["POST"])
def reject_email_reset(user=None):
	frappe.throw(_("Ask R10 or a PIN-verified R02 to reset your account."), frappe.PermissionError)


def require_pin_changed(employee):
	# Use the current locked row, not a transaction snapshot from before revocation.
	row = station_auth.lock_employee(employee)
	if row and row.tc_pin_reset_required:
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


def _authorize_reset(proof, token=None):
	if _has_role("TC R10"):
		return
	if not _has_role("TC R02") or not isinstance(proof, str) or not proof:
		frappe.throw(_("A supervisor station PIN proof is required."), frappe.PermissionError)
	try:
		session = station_auth.consume_pin_proof(token, proof)
		if session.user == frappe.session.user:
			return
	except BlockedError:
		pass
	frappe.throw(_("A supervisor station PIN proof is required."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def reset_password(user, new_password, proof=None, token=None):
	validate_password(new_password)
	_authorize_reset(proof, token)
	if user in frappe.STANDARD_USERS or not frappe.db.exists("User", user):
		frappe.throw(_("Choose an employee account."))
	_record_password(user, new_password, reset=True)


@frappe.whitelist(methods=["POST"])
def reset_pin(employee, new_pin, proof=None, token=None):
	_authorize_reset(proof, token)
	station_auth.set_pin(employee, new_pin)
	frappe.db.set_value("Employee", employee, "tc_pin_reset_required", 1)
	audit.log("Update", "Employee", employee, new={"event": "PIN Reset"})
