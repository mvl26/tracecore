"""RPC tracecore.v1.audit.* — tra cứu Audit Log (theo permission người gọi) và phiếu giám sát KSNK (FEAT-060).

Phiếu giám sát (M12, ADR-015):
- Trạm/PDA (SCR-52, Station Function ``AUDIT``): ``context`` (mẫu + khoa, cũng là snapshot offline) và
  ``submit_session`` (``@idempotent``, phát lại offline ≥ 4 giờ, ADR-003). Người giám sát = nhân viên của phiên thẻ.
- Desk / Page ``tc-ksnk`` (SCR-50, SCR-53): ``template_board``, ``save_template``, ``approve_template``,
  ``new_version``, ``schedule_board``, ``save_schedule``, ``compliance_board``, ``open_nc``, ``dismiss_nc``.
"""

import frappe
from frappe.utils import cint

from tracecore.compliance_audit import board, nc, pda
from tracecore.core import sync
from tracecore.core.client_time import check_not_future, parse_client_ts, to_system_time
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import (
	AUDIT_ROLES,
	current_station_session,
	require_any_role,
	run_at_step,
	station_session,
)

AUDIT_FUNCTION = "AUDIT"

MAX_LIMIT = 500
FIELDS = [
	"name",
	"timestamp",
	"user",
	"station",
	"device",
	"action",
	"ref_doctype",
	"ref_name",
	"reason",
	"old_value",
	"new_value",
	"request_id",
	"client_ts",
]


@frappe.whitelist()
def query(ref_doctype=None, ref_name=None, user=None, station=None, from_ts=None, to_ts=None, limit=50):
	filters = {
		key: value
		for key, value in (
			("ref_doctype", ref_doctype),
			("ref_name", ref_name),
			("user", user),
			("station", station),
		)
		if value
	}
	if from_ts and to_ts:
		filters["timestamp"] = ("between", [from_ts, to_ts])
	elif from_ts:
		filters["timestamp"] = (">=", from_ts)
	elif to_ts:
		filters["timestamp"] = ("<=", to_ts)
	limit = min(cint(limit) or 50, MAX_LIMIT)
	return frappe.get_list(
		"Audit Log",
		filters=filters,
		fields=FIELDS,
		order_by="timestamp desc, name desc",
		limit_page_length=limit,
	)


# --- phiếu giám sát trên trạm/PDA (SCR-52) ------------------------------------------------------------------------


def _observer():
	session = current_station_session()
	return session.employee if session else None


def _ok(result):
	return result if "ok" in result else {"ok": True, **result}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*AUDIT_ROLES)
def context(station, client_ts=None, token=None):
	"""Mẫu phiếu đã duyệt (kèm mục) và khoa được làm phiếu; người giám sát = nhân viên của phiên."""
	require_any_role(*AUDIT_ROLES)
	timestamp = parse_client_ts(client_ts)
	on = to_system_time(timestamp)
	return _ok(run_at_step(AUDIT_FUNCTION, station, timestamp, lambda: pda.context(_observer(), on)))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*AUDIT_ROLES, offline=True)
@idempotent
def submit_session(
	station,
	audit_template,
	department,
	answers=None,
	location=None,
	mode=None,
	subject_role=None,
	subject_employee=None,
	supplier=None,
	started_at=None,
	session_uuid=None,
	client_ts=None,
	token=None,
	device_episode=None,  # FEAT-062 (FR-M12-07): đợt thiết bị của phiếu gói dự phòng
	environment_zone=None,  # FEAT-070 (FR-M15-02, FR-M15-06): vùng vệ sinh của phiếu VSMT/hạ tầng
	next_due=None,  # FEAT-070: hạn kiểm tra hạ tầng kế tiếp (trống = theo chu kỳ của mẫu)
):
	"""Tạo và ghi sổ phiếu giám sát (FR-M12-04); khi phát lại (`X-TC-Replay`) ngày phiếu = ngày của `client_ts`."""
	require_any_role(*AUDIT_ROLES)
	timestamp = parse_client_ts(client_ts)
	replay = sync.is_replay()
	if replay:
		check_not_future(timestamp)
	values = {
		"audit_template": audit_template,
		"department": department,
		"answers": answers,
		"location": location,
		"mode": mode,
		"subject_role": subject_role,
		"subject_employee": subject_employee,
		"supplier": supplier,
		"device_episode": device_episode,  # FEAT-062
		"environment_zone": environment_zone,  # FEAT-070
		"next_due": next_due,  # FEAT-070
		"started_at": to_system_time(parse_client_ts(started_at)) if started_at else None,
		"session_uuid": session_uuid,
	}
	return _ok(
		run_at_step(
			AUDIT_FUNCTION,
			station,
			timestamp,
			lambda: pda.submit(_observer(), values, to_system_time(timestamp), replay),
			"Audit Session",
			session_uuid,
		)
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*AUDIT_ROLES, offline=True)
@idempotent
def record_opportunity(
	station,
	audit_template,
	department,
	session_uuid,
	opportunity,
	location=None,
	mode=None,
	started_at=None,
	client_ts=None,
	token=None,
):
	"""FEAT-061 (SCR-51, FR-M12-04, BRU-AUD-002): ghi một cơ hội vệ sinh tay vào phiếu Nháp ``session_uuid`` (tạo ở lần
	đầu); ``opportunity`` = {uuid, subject_role, subject_employee, moment, action, technique_ok, glove_instead}. Ghi sổ
	phiếu bằng ``submit_session`` cùng ``session_uuid``."""
	require_any_role(*AUDIT_ROLES)
	timestamp = parse_client_ts(client_ts)
	replay = sync.is_replay()
	if replay:
		check_not_future(timestamp)
	values = {
		"audit_template": audit_template,
		"department": department,
		"session_uuid": session_uuid,
		"opportunity": opportunity,
		"location": location,
		"mode": mode,
		"started_at": to_system_time(parse_client_ts(started_at)) if started_at else None,
	}
	return _ok(
		run_at_step(
			AUDIT_FUNCTION,
			station,
			timestamp,
			lambda: pda.record_opportunity(_observer(), values, to_system_time(timestamp), replay),
			"Audit Session",
			session_uuid,
		)
	)


# --- Desk / Page tc-ksnk (SCR-50, SCR-53) ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def template_board(template=None):
	return board.template_board(template)


@frappe.whitelist(methods=["POST"])
def save_template(values):
	return board.save_template(frappe.parse_json(values))


@frappe.whitelist(methods=["POST"])
def approve_template(template):
	return board.approve_template(template)


@frappe.whitelist(methods=["POST"])
def new_version(template):
	return board.new_version(template)


@frappe.whitelist(methods=["GET"])
def schedule_board(on=None):
	return board.schedule_board(on)


@frappe.whitelist(methods=["POST"])
def save_schedule(values):
	return board.save_schedule(frappe.parse_json(values))


@frappe.whitelist(methods=["GET"])
def compliance_board(from_date=None, to_date=None, audit_type=None, template_code=None, profession=None):
	return board.compliance_board(
		{
			"from_date": from_date,
			"to_date": to_date,
			"audit_type": audit_type,
			"template_code": template_code,
			"profession": profession,
		}
	)


@frappe.whitelist(methods=["POST"])
def open_nc(session):
	return {"ok": True, "incident": nc.open_nc(session)}


@frappe.whitelist(methods=["POST"])
def dismiss_nc(session, reason=None):
	nc.dismiss_nc(session, reason)
	return {"ok": True}
