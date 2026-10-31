"""RPC tracecore.v1.usage.* — màn T8 quét sử dụng (SCR-37 PDA, FEAT-027, UC-13).

Lớp mỏng trên `tracecore.reprocessing.usage`: phiên trạm thẻ nhân viên (`@station_session`, token trong body POST) →
kiểm quyền R08 → gọi dịch vụ. Từ chối nghiệp vụ (`BlockedError`) thành ``{"ok": false, "error": {...}}`` kèm mã HTTP và
Audit Log `Reject` (FR-M2-18.2, xem `_common.run_at_step`). RPC ghi (`confirm`, `set_patient_code`) dùng ``@idempotent``.
`reveal_patient_code` chạy bằng phiên Desk của R01/R02/System Manager (không phải phiên trạm), ghi Audit không chứa mã.
"""

import frappe
from frappe import _

from tracecore.core import crypto, gs1, sync
from tracecore.core.client_time import check_not_future, parse_client_ts, to_system_time
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import usage as usage_service
from tracecore.v1._common import (
	USAGE_ROLES,
	current_station_session,
	reject_block,
	require_any_role,
	run_at_step,
	station_session,
)

FUNCTION = usage_service.FUNCTION
REVEAL_ROLES = ("TC R01", "TC R02", "System Manager")


def _employee():
	session = current_station_session()
	return session.employee if session else None


def _run(station, client_ts, call, ref_doctype=None, ref_name=None, raw=None):
	"""Chạy `call()` ở trạm T8; trả ``{"ok": true, **kết quả}`` hoặc body từ chối nghiệp vụ."""
	timestamp = parse_client_ts(client_ts)
	result = run_at_step(FUNCTION, station, timestamp, lambda: call(timestamp), ref_doctype, ref_name, raw)
	return result if "ok" in result else {"ok": True, **result}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*USAGE_ROLES)
def scan(raw, station, client_ts=None, token=None):
	"""Quét Cycle ID (SCR-37 bước 1): kiểm hiệu lực rồi trả ``{"ok": true, "card": {...}}`` kèm cảnh báo khác khoa.

	Chỉ đọc nhưng mọi lần quét bị chặn đều ghi Audit `Reject` (FR-M2-18.2): 404 không có gói, 409 Đã dùng/Thu
	hồi/Hết hiệu lực/Quá hạn/chưa cấp phát/bộ hết vòng đời, 422 mã không phải gói.
	"""
	require_any_role(*USAGE_ROLES)
	scanned = gs1.parse_scan(raw)
	ref = "Pack" if scanned["type"] == "pack" else None
	return _run(
		station,
		client_ts,
		lambda _ts: {"card": usage_service.scan(raw, station, _employee())},
		ref,
		scanned["id"] if ref else None,
		raw,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*USAGE_ROLES, offline=True)
@idempotent
def confirm(
	cycle_id,
	station,
	patient_code=None,
	surgery_code=None,
	surgeon=None,
	room=None,
	emergency=0,
	department_reason=None,
	patient_code_enc=None,
	client_ts=None,
	token=None,
):
	"""Xác nhận sử dụng (SCR-37 bước 2): Usage Record, Pack → Used, Set Unit → Chờ tiếp nhận; không trả mã rõ.

	PDA offline gửi `patient_code_enc` (mã BN mã hóa bằng public key của site, A-40 D2) thay cho `patient_code`.
	Khi phát lại (`X-TC-Replay`), thời điểm sử dụng = `client_ts` (ADR-003).
	"""
	require_any_role(*USAGE_ROLES)
	replay = sync.is_replay()

	def call(ts):
		if replay:
			check_not_future(ts)  # thời điểm sử dụng do trạm báo: cũ được, tương lai thì không (review I5)
		code = _decrypt(patient_code_enc) if patient_code_enc else patient_code
		return usage_service.confirm(
			cycle_id,
			station,
			_employee(),
			code,
			surgery_code,
			surgeon,
			room,
			emergency,
			department_reason,
			ts,
			used_at=to_system_time(ts) if replay else None,
		)

	return _run(station, client_ts, call, "Pack", cycle_id)


def _decrypt(enc):
	try:
		return crypto.decrypt_patient_code(enc)
	except ValueError:
		raise BlockedError(
			Block(
				"PATIENT_CODE_UNREADABLE",
				_("Patient code cannot be read"),
				_("The encrypted patient code from the PDA could not be decrypted."),
				_("Do not use the pack yet; R02 checks the usage on the Desk."),
			)
		) from None


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*USAGE_ROLES)
@idempotent
def set_patient_code(usage, patient_code, station, client_ts=None, token=None):
	"""Nhập bổ sung mã bệnh nhân của ca cấp cứu trong 24 giờ (FR-M2-17.2)."""
	require_any_role(*USAGE_ROLES)
	return _run(
		station,
		client_ts,
		lambda _ts: usage_service.set_patient_code(usage, patient_code, _employee()),
		"Usage Record",
		usage,
	)


@frappe.whitelist(methods=["POST"])
@idempotent
def reveal_patient_code(usage, reason=None, client_ts=None):
	"""Xem mã bệnh nhân đầy đủ (R01/R02/System Manager, lý do bắt buộc, Audit `View Patient Code`)."""
	require_any_role(*REVEAL_ROLES)
	timestamp = parse_client_ts(client_ts)
	try:
		code = usage_service.reveal_patient_code(usage, reason)
	except BlockedError as error:
		return reject_block(error.block, "Usage Record", usage, client_ts=timestamp)
	return {"ok": True, "usage": usage, "patient_code": code}
