"""RPC tracecore.v1.exposure.* — báo phơi nhiễm (SCR-63 PDA/DEPT) và hồ sơ phơi nhiễm (SCR-64) (FEAT-071; FR-M16-01..09;
UC-55; A-137; ADR-003).

- ``report`` (POST, phiên thẻ trạm, ``@idempotent``, phát lại offline được): nhân viên của phiên báo cho chính mình.
- ``report_portal`` (POST, đăng nhập, ``@idempotent``): Cổng khoa; R08/R12 báo thay nhân viên cùng khoa.
- ``portal_context``, ``my_records`` (GET): dữ liệu trang Cổng khoa, hồ sơ của chính nhân viên (UC-55 A4).
- ``dashboard``, ``detail`` (GET) và ``record_handling``, ``followup_done``, ``cancel``, ``reveal_source_code``,
  ``approve_template``, ``approve_requirement`` (POST, RPC Desk không ``@idempotent`` như các RPC Desk khác).

Từ chối nghiệp vụ trả body ``{"ok": false, "error": {...}}`` (``reject_block``), không bật msgprint.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime, strip_html

from tracecore.core import crypto, sync
from tracecore.core.client_time import ClientTimestampError, parse_client_ts, to_system_time
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.occupational_safety import config, dashboard, patient_code
from tracecore.occupational_safety import exposure as service
from tracecore.v1._common import (
	BadRequestError,
	current_station_session,
	reject_block,
	require_any_role,
	run_at_step,
	station_session,
)

DOCTYPE = service.DOCTYPE
FUNCTION = "EXPOSURE"
# Mọi nhân viên có thẻ/tài khoản TraceCore báo được phơi nhiễm của mình (FR-M16-05.2); R13 không thao tác trạm
EXPOSURE_ROLES = (*(f"TC R{n:02d}" for n in range(1, 13)), "System Manager")
PROXY_ROLES = ("TC R08", "TC R12")
MANAGER_ROLES = service.MANAGER_ROLES
SCREEN_ROLES = (*MANAGER_ROLES, "TC R13")


def _text(value, name, limit=140):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	value = (value or "").strip()
	return value[:limit] or None


def _occurred(value):
	try:
		return to_system_time(parse_client_ts(value))
	except ClientTimestampError:
		raise BadRequestError(_("occurred_at must be an ISO 8601 time with offset.")) from None


def _values(employee, exposure_type, occurred_at, activity, device, source_known, code):
	return {
		"employee": employee,
		"exposure_type": exposure_type,
		"occurred_at": _occurred(occurred_at),
		"activity": _text(activity, "activity"),
		"device": _text(device, "device"),
		"source_known": source_known,
		"source_patient_code": _text(code, "source_patient_code", 64),
	}


def _receipt(doc):
	return {
		"name": doc.name,
		"exposure_type": doc.exposure_type,
		"occurred_at": str(doc.occurred_at),
		"status": doc.status,
		"procedure": service.procedure(),
	}


def _decrypt(enc):
	try:
		return crypto.decrypt_patient_code(enc)
	except ValueError:
		raise BlockedError(
			Block(
				"PATIENT_CODE_UNREADABLE",
				_("Patient code cannot be read"),
				_("The encrypted patient code from the PDA could not be decrypted."),
				_("Send the report without the patient code; the supervisor adds it on the Desk."),
			)
		) from None


# --- SCR-63 PDA ---------------------------------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*EXPOSURE_ROLES, offline=True)
@idempotent
def report(
	station,
	exposure_type=None,
	occurred_at=None,
	activity=None,
	device=None,
	source_known=None,
	source_patient_code=None,
	source_patient_code_enc=None,
	client_ts=None,
	token=None,
):
	"""Báo phơi nhiễm ban đầu từ PDA (≤ 3 bước, FR-M16-01); nhân viên = người của phiên thẻ.

	PDA offline gửi `source_patient_code_enc` (mã hóa bằng public key của site) thay cho mã rõ. Phát lại offline
	(`X-TC-Replay`): giờ báo = `client_ts` (ADR-003); thông báo đi khi server nhận (UC-55 A2).
	"""
	require_any_role(*EXPOSURE_ROLES)
	timestamp = parse_client_ts(client_ts)
	employee = current_station_session().employee
	replay = sync.is_replay()

	def call():
		code = _decrypt(source_patient_code_enc) if source_patient_code_enc else source_patient_code
		values = _values(employee, exposure_type, occurred_at, activity, device, source_known, code)
		if replay:
			values["reported_at"] = _replay_reported_at(values, timestamp)
		doc = service.create_report(values, channel="PDA")
		return {"ok": True, "exposure": _receipt(doc)}

	return run_at_step(FUNCTION, station, timestamp, call, DOCTYPE, None)


# --- SCR-63 Cổng khoa ---------------------------------------------------------------------------------------------


def _require_login():
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Sign in to report an exposure."))


def _proxy_departments(user=None):
	"""Khoa mà người gọi được báo thay: R12 theo User Permission Department, R08 theo khoa của Employee."""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if not roles & set(PROXY_ROLES):
		return set()
	departments = set()
	if "TC R12" in roles:
		departments |= set(
			frappe.get_all(
				"User Permission", filters={"user": user, "allow": "Department"}, pluck="for_value"
			)
		)
	own = service.employee_of(user)
	if own:
		department = frappe.db.get_value("Employee", own, "department")
		if department:
			departments.add(department)
	return departments


def _target_employee(employee):
	me = service.employee_of()
	if not employee or employee == me:
		if not me:
			raise BlockedError(
				Block(
					"EXPOSURE_NO_EMPLOYEE",
					_("Your account is not linked to a staff record"),
					_("The exposure must belong to a staff member, but your account has no staff record."),
					_("Ask the department nurse or the infection control team to report it for you."),
				)
			)
		return me
	department = frappe.db.get_value("Employee", {"name": employee, "status": "Active"}, "department")
	if not department or department not in _proxy_departments():
		raise BlockedError(
			Block(
				"EXPOSURE_NOT_ALLOWED",
				_("Cannot report for this staff member"),
				_("You can report for yourself or for staff of your own department only."),
				_("Choose a staff member of your department, or ask them to report it themselves."),
			)
		)
	return employee


@frappe.whitelist(methods=["POST"])
@idempotent
def report_portal(
	exposure_type=None,
	occurred_at=None,
	activity=None,
	device=None,
	source_known=None,
	source_patient_code=None,
	employee=None,
	client_ts=None,
):
	"""Báo phơi nhiễm trên Cổng khoa (FR-M16-01; A-137 Q4)."""
	_require_login()
	timestamp = parse_client_ts(client_ts)
	try:
		target = _target_employee(_text(employee, "employee"))
		values = _values(
			target, exposure_type, occurred_at, activity, device, source_known, source_patient_code
		)
		if sync.is_replay():
			values["reported_at"] = _replay_reported_at(values, timestamp)
		doc = service.create_report(values, channel="Department Portal")
	except BlockedError as error:
		return reject_block(error.block, DOCTYPE, None, client_ts=timestamp)
	return {"ok": True, "exposure": _receipt(doc)}


@frappe.whitelist(methods=["GET"])
def portal_context():
	"""Dữ liệu trang Cổng khoa: người báo, khoa, đồng nghiệp được báo thay, loại phơi nhiễm, quy trình, hồ sơ của tôi."""
	_require_login()
	me = service.employee_of()
	info = frappe.db.get_value("Employee", me, ["employee_name", "department"], as_dict=True) if me else None
	departments = _proxy_departments()
	colleagues = (
		frappe.get_all(
			"Employee",
			filters={"status": "Active", "department": ["in", list(departments)]},
			fields=["name as employee", "employee_name", "department"],
			order_by="employee_name",
			limit=500,
		)
		if departments
		else []
	)
	return {
		"employee": me,
		"employee_name": info.employee_name if info else None,
		"department": info.department if info else None,
		"colleagues": colleagues,
		"types": list(config.EXPOSURE_TYPES),
		"procedure": service.procedure(),
		"records": service.my_records(),
	}


@frappe.whitelist(methods=["GET"])
def my_records():
	_require_login()
	return service.my_records()


# --- SCR-64 -------------------------------------------------------------------------------------------------------


def _blocked_body(error, name=None):
	return reject_block(error.block, DOCTYPE, name)


def _savepoint(name, fn):
	frappe.db.savepoint("tc_exposure")
	try:
		return fn()
	except BlockedError as error:
		frappe.db.rollback(save_point="tc_exposure")
		return _blocked_body(error, name)


@frappe.whitelist(methods=["GET"])
def dashboard_data():
	require_any_role(*SCREEN_ROLES)
	return dashboard.build()


@frappe.whitelist(methods=["GET"])
def detail(name):
	require_any_role(*MANAGER_ROLES)
	return dashboard.detail(name)


@frappe.whitelist(methods=["POST"])
def record_handling(name, first_aid_done=0, first_aid_at=None, prophylaxis=None, prophylaxis_started_at=None):
	"""R11 ghi sơ cứu và chỉ định dự phòng (UC-55 bước 3-4)."""
	require_any_role(*MANAGER_ROLES)
	return _savepoint(
		name,
		lambda: {
			"ok": True,
			"detail": dashboard.detail(
				service.record_handling(
					name,
					first_aid_done,
					first_aid_at or None,
					prophylaxis or None,
					prophylaxis_started_at or None,
				).name
			),
		},
	)


@frappe.whitelist(methods=["POST"])
def followup_done(name, row, done_on):
	require_any_role(*MANAGER_ROLES)
	return _savepoint(
		name,
		lambda: {"ok": True, "detail": dashboard.detail(service.mark_followup_done(name, row, done_on).name)},
	)


@frappe.whitelist(methods=["POST"])
def cancel(name, reason=None):
	require_any_role(*MANAGER_ROLES)
	return _savepoint(
		name, lambda: {"ok": True, "detail": dashboard.detail(service.cancel(name, reason).name)}
	)


@frappe.whitelist(methods=["POST"])
def reveal_source_code(name, reason=None):
	"""Mã BN nguồn đầy đủ: R01/R11, lý do bắt buộc, Audit Log `View Patient Code` (ADR-010)."""
	require_any_role(*patient_code.REVEAL_ROLES, "System Manager")
	try:
		code = patient_code.reveal(DOCTYPE, name, reason)
	except BlockedError as error:
		return _blocked_body(error, name)
	return {"ok": True, "name": name, "source_patient_code": code}


def _approve(fn, name):
	"""Nút Duyệt trên form Desk: lỗi nghiệp vụ trả body để form hiện cảnh báo inline (không msgprint)."""
	frappe.db.savepoint("tc_exposure_approve")
	try:
		doc = fn(name)
	except frappe.PermissionError:
		frappe.db.rollback(save_point="tc_exposure_approve")
		raise
	except frappe.ValidationError as error:
		frappe.db.rollback(save_point="tc_exposure_approve")
		frappe.clear_messages()
		return {
			"ok": False,
			"error": {
				"title": _("Not approved"),
				"reason": strip_html(str(error)),
				"action": _("Correct the record, save it, then approve again."),
			},
		}
	return {"ok": True, "name": doc.name, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def approve_template(name):
	"""R01 duyệt một phiên bản mẫu theo dõi (A-137 Q3)."""
	return _approve(config.approve_template, name)


@frappe.whitelist(methods=["POST"])
def approve_requirement(name):
	"""R01 duyệt yêu cầu tiêm chủng (A-137 f)."""
	return _approve(config.approve_requirement, name)


def _replay_reported_at(values, timestamp):
	"""Giờ báo của gói phát lại = client_ts, kẹp trong [giờ phơi nhiễm, bây giờ] để không báo lùi/tiến giờ."""
	reported = get_datetime(to_system_time(timestamp))
	return min(max(reported, get_datetime(values["occurred_at"])), now_datetime())
