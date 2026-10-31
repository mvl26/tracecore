"""RPC tracecore.v1.issue.* — màn T7 cấp phát (SCR-12 kiosk, SCR-36 PDA, FEAT-026, UC-12).

Lớp mỏng trên `tracecore.reprocessing.issuing`: phiên trạm thẻ nhân viên (`@station_session`, token trong body POST) →
kiểm quyền R06 → gọi dịch vụ. Từ chối nghiệp vụ (`BlockedError`) thành ``{"ok": false, "error": {...}}`` kèm mã HTTP và
Audit Log `Reject` (xem `_common.run_at_step`). RPC ghi (`create`, `add_pack`, `remove_pack`, `sign`, `submit`) dùng
``@idempotent``; `departments`, `context` chỉ đọc. Phiếu dựng ở nháp (`create`), nhận gói và chữ ký, rồi `submit` ghi sổ.
"""

import frappe

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import issuing
from tracecore.v1._common import (
	STORAGE_ROLES,
	current_station_session,
	require_any_role,
	run_at_step,
	station_session,
)

STEP = issuing.STEP  # màn cấp phát chỉ chạy ở trạm bước T7
ISSUE_ROLES = STORAGE_ROLES  # R06 (KTV kho vô khuẩn / cấp phát) và System Manager


def _run(
	station, client_ts, call, ref_doctype=None, ref_name=None, raw=None, entry_mode=None, manual_reason=None
):
	"""Chạy `call()` ở trạm T7; trả ``{"ok": true, **kết quả}`` hoặc body từ chối nghiệp vụ."""
	timestamp = parse_client_ts(client_ts)
	result = run_at_step(
		STEP,
		station,
		timestamp,
		lambda: call(timestamp),
		ref_doctype,
		ref_name,
		raw,
		entry_mode,
		manual_reason,
	)
	return result if "ok" in result else {"ok": True, **result}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ISSUE_ROLES)
def departments(station=None, client_ts=None, token=None):
	"""Danh sách khoa nhận cấp phát (chỉ đọc)."""
	require_any_role(*ISSUE_ROLES)
	return {"ok": True, "departments": issuing.departments()}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ISSUE_ROLES)
def context(department, station=None, issue_note=None, client_ts=None, token=None):
	"""UC-12 bước 1: tồn khoa, cơ số và tồn kho vô khuẩn theo loại bộ của khoa (chỉ đọc)."""
	require_any_role(*ISSUE_ROLES)
	return _run(
		station, client_ts, lambda _ts: issuing.context(department, issue_note), "Department", department
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ISSUE_ROLES)
@idempotent
def create(department, station, client_ts=None, token=None):
	"""Mở phiếu nháp cho khoa (hoặc mở lại phiếu nháp đang có của cùng người, trạm, khoa)."""
	require_any_role(*ISSUE_ROLES)
	session = current_station_session()
	return _run(
		station,
		client_ts,
		lambda ts: {"issue": issuing.create(department, station, session.employee if session else None, ts)},
		"Department",
		department,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ISSUE_ROLES)
@idempotent
def add_pack(
	issue_note,
	raw,
	station,
	note=None,
	move=0,
	entry_mode="Scan",
	manual_reason=None,
	client_ts=None,
	token=None,
):
	"""Quét một gói vào phiếu (Cycle ID hoặc DataMatrix). Gói hạn xa hơn gói FEFO cần `note`; `move` chuyển gói từ phiếu
	nháp khác sang."""
	require_any_role(*ISSUE_ROLES)
	scanned = gs1.parse_scan(raw)
	ref = "Pack" if scanned["type"] == "pack" else None
	return _run(
		station,
		client_ts,
		lambda ts: {"issue": issuing.add_pack(issue_note, raw, station, note, move, ts)},
		ref,
		scanned["id"] if ref else None,
		scanned["raw"],
		entry_mode,
		manual_reason,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ISSUE_ROLES)
@idempotent
def remove_pack(issue_note, cycle_id, station, client_ts=None, token=None):
	"""Bỏ một gói quét nhầm khỏi phiếu nháp."""
	require_any_role(*ISSUE_ROLES)
	return _run(
		station,
		client_ts,
		lambda ts: {"issue": issuing.remove_pack(issue_note, cycle_id, station, ts)},
		"Issue Note",
		issue_note,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ISSUE_ROLES)
@idempotent
def sign(issue_note, card, station, method="Card", signature=None, reason=None, client_ts=None, token=None):
	"""Người nhận quét thẻ và ký (`method` Card hoặc Touch kèm ảnh chữ ký PNG). Người nhận khác khoa cần `reason`."""
	require_any_role(*ISSUE_ROLES)
	return _run(
		station,
		client_ts,
		lambda ts: {"issue": issuing.sign(issue_note, card, station, method, signature, reason, ts)},
		"Issue Note",
		issue_note,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ISSUE_ROLES)
@idempotent
def submit(issue_note, station, approver_proof=None, client_ts=None, token=None):
	"""Xác nhận phiếu đã ký: Pack Đã cấp phát, Set Unit Tại khoa.

	Vượt cơ số tối đa cần `approver_proof`: R02 quét thẻ + nhập PIN trên kiosk này qua ``v1.station.verify_approver``
	(proof dùng một lần gắn với phiên trạm đang cấp phát).
	"""
	require_any_role(*ISSUE_ROLES)
	session = current_station_session()
	return _run(
		station,
		client_ts,
		lambda ts: issuing.submit(issue_note, station, approver_proof, session.name if session else None, ts),
		"Issue Note",
		issue_note,
	)
