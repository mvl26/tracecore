"""RPC tracecore.v1.receive.* — màn T1 tiếp nhận (SCR-05, SCR-34, FEAT-019): mở phiếu, quét bộ, xác nhận, ghi sổ.

Lớp mỏng trên `tracecore.reprocessing.receiving`, theo khuôn `v1.wash`: phiên thẻ nhân viên (`station_session`, token
trong body) → `@idempotent` → kiểm định dạng tham số (400) → gọi dịch vụ. Từ chối nghiệp vụ (`BlockedError`) thành
``{"ok": false, "error": {...}}`` kèm mã HTTP và Audit Log `Reject`, không ném lại (xem `_common.run_at_step`). Mọi RPC
chỉ chạy ở trạm bước T1; người nhận là Employee của phiên thẻ (không nhận từ tham số).
"""

import json

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import receiving
from tracecore.v1._common import (
	RECEIVE_ROLES,
	BadRequestError,
	current_station_session,
	require_any_role,
	run_at_step,
	station_session,
)

STEP = receiving.STEP
TRUE_STRINGS = ("1", "true", "yes", "on")


# --- Định dạng tham số (400) -------------------------------------------------------------------------


def _text(value, name, required=False):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	if required and not value:
		raise BadRequestError(_("{0} must be a string.").format(name))
	return value or None


def _flag(value):
	if isinstance(value, bool):
		return value
	if isinstance(value, int):
		return value != 0
	if isinstance(value, str):
		return value.strip().lower() in TRUE_STRINGS
	return False


def _lines(value):
	"""`lines` là list (hoặc chuỗi JSON của list) các ``{"instrument": str, "confirmed": bool/int}``; không có → None."""
	if value is None:
		return None
	message = _("lines must be a list of objects with an instrument and a confirmed flag.")
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			raise BadRequestError(message) from None
	if not isinstance(value, list) or not all(
		isinstance(row, dict) and isinstance(row.get("instrument"), str) for row in value
	):
		raise BadRequestError(message)
	return [{"instrument": row["instrument"], "confirmed": _flag(row.get("confirmed", 1))} for row in value]


def _receiver():
	session = current_station_session()
	return session.employee if session else None


def _set_ref(raw):
	scanned = gs1.parse_scan(raw)
	return ("Set Unit" if scanned["type"] == "set" else None), scanned["id"], scanned["raw"]


def _receipt_ref(receipt):
	return ("Dirty Receipt", receipt) if isinstance(receipt, str) and receipt else (None, None)


# --- Mở, tiếp tục, hủy phiếu ----------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RECEIVE_ROLES)
@idempotent
def open(station, raw=None, department=None, deliverer_name=None, client_ts=None, token=None):
	"""Mở phiếu nháp từ thẻ người giao `raw`, hoặc từ `department` + `deliverer_name` (người giao không có thẻ).

	Không truyền gì: tiếp tục phiếu nháp gần nhất của người đăng nhập tại trạm. Trả ``{"ok": true, **phiếu}`` hoặc,
	khi chưa có phiếu, ``{"ok": true, "receipt": null, "departments": [...]}`` để chọn khoa khi không có thẻ.
	"""
	require_any_role(*RECEIVE_ROLES)
	raw, department = _text(raw, "raw"), _text(department, "department")
	deliverer_name = _text(deliverer_name, "deliverer_name")
	timestamp = parse_client_ts(client_ts)

	def call():
		opened = receiving.open_receipt(station, _receiver(), timestamp, raw, department, deliverer_name)
		if opened is None:
			return {"ok": True, "receipt": None, "departments": receiving.departments()}
		return {"ok": True, **opened}

	return run_at_step(
		STEP, station, timestamp, call, None, None, gs1.parse_scan(raw)["raw"] if raw else None
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RECEIVE_ROLES)
@idempotent
def discard(receipt, station, client_ts=None, token=None):
	"""Bỏ phiếu nháp (giữ bản ghi cho Audit)."""
	require_any_role(*RECEIVE_ROLES)
	receipt = _text(receipt, "receipt", required=True)
	timestamp = parse_client_ts(client_ts)

	def call():
		receiving.discard(receipt, station, _receiver())
		return {"ok": True, "receipt": None, "departments": receiving.departments()}

	return run_at_step(STEP, station, timestamp, call, *_receipt_ref(receipt))


# --- Quét bộ, xác nhận, ghi sổ ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RECEIVE_ROLES)
@idempotent
def scan_set(receipt, raw, station, force_reason=None, reviewer_proof=None, client_ts=None, token=None):
	"""Quét một Set ID vào phiếu: trả ``{"ok": true, "duplicate", "item", "summary"}``; `item` có đủ dòng BOM + ảnh.

	`force_reason` + `reviewer_proof` (PIN proof của R02 đang đăng nhập, `v1.station.verify_pin`) chỉ dùng để tiếp nhận
	cưỡng bức bộ bị từ chối (FR-M2-02.2).
	"""
	require_any_role(*RECEIVE_ROLES)
	receipt = _text(receipt, "receipt", required=True)
	raw = _text(raw, "raw", required=True)
	force_reason = _text(force_reason, "force_reason")
	reviewer_proof = _text(reviewer_proof, "reviewer_proof")
	timestamp = parse_client_ts(client_ts)
	session = current_station_session()
	ref_doctype, ref_name, shown = _set_ref(raw)
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {
			"ok": True,
			**receiving.scan_set(
				receipt,
				raw,
				station,
				_receiver(),
				timestamp,
				force_reason=force_reason,
				session=session.name if session else None,
				reviewer_proof=reviewer_proof,
			),
		},
		ref_doctype,
		ref_name,
		shown,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RECEIVE_ROLES)
@idempotent
def confirm_line(
	receipt,
	set_id,
	station,
	lines=None,
	confirm_all=0,
	note=None,
	finalize=0,
	ack_incomplete=0,
	client_ts=None,
	token=None,
):
	"""Tick từng dòng / Xác nhận tất cả, ghi chú bất thường, Xác nhận bộ (FR-M2-23); trả ``{"ok": true, "item"}``."""
	require_any_role(*RECEIVE_ROLES)
	receipt = _text(receipt, "receipt", required=True)
	set_id = _text(set_id, "set_id", required=True)
	rows, note = _lines(lines), _text(note, "note")
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {
			"ok": True,
			"item": receiving.confirm_line(
				receipt,
				set_id,
				station,
				_receiver(),
				lines=rows,
				confirm_all=_flag(confirm_all),
				note=note,
				finalize=_flag(finalize),
				ack_incomplete=_flag(ack_incomplete),
			),
		},
		*_receipt_ref(receipt),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RECEIVE_ROLES)
@idempotent
def attach_photo(receipt, set_id, file_name, content, station, client_ts=None, token=None):
	"""Đính ảnh chụp bất thường (base64, JPEG/PNG/WebP ≤ 5 MiB) vào một bộ; trả ``{"ok": true, "item"}``."""
	require_any_role(*RECEIVE_ROLES)
	receipt = _text(receipt, "receipt", required=True)
	set_id = _text(set_id, "set_id", required=True)
	file_name, content = _text(file_name, "file_name"), _text(content, "content", required=True)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {
			"ok": True,
			"item": receiving.attach_photo(receipt, set_id, station, _receiver(), file_name, content),
		},
		*_receipt_ref(receipt),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RECEIVE_ROLES)
@idempotent
def submit(receipt, station, client_ts=None, token=None):
	"""Ghi sổ phiếu: mở chu trình, ghim BOM và ghi cổng T1 Đạt cho từng bộ (FR-M2-01.4); xem `receiving.submit`."""
	require_any_role(*RECEIVE_ROLES)
	receipt = _text(receipt, "receipt", required=True)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {"ok": True, **receiving.submit(receipt, station, _receiver(), timestamp)},
		*_receipt_ref(receipt),
	)
