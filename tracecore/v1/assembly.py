"""RPC tracecore.v1.assembly.* — màn T3 kiểm đếm lắp ráp theo BOM (SCR-07, FEAT-020): mở bộ, ghi dòng, xác nhận thiếu, ghi sổ.

Lớp mỏng trên `tracecore.reprocessing.assembly`, theo khuôn `v1.pack`/`v1.wash`: phiên thẻ nhân viên (`station_session`,
token trong body) → `@idempotent` → kiểm định dạng tham số (400) → gọi dịch vụ ở trạm bước T3 (`run_at_step`). Từ chối
nghiệp vụ (`BlockedError`) thành ``{"ok": false, "error": {...}}`` kèm mã HTTP và Audit Log `Reject`, không ném lại.
`confirm_shortage` chỉ cho R02 (và System Manager) và cần PIN proof của chính phiên đó (`v1.station.verify_pin`).
"""

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import assembly as service
from tracecore.v1._common import (
	BadRequestError,
	current_station_session,
	require_any_role,
	run_at_step,
	station_session,
)

FUNCTION = service.FUNCTION
ASSEMBLY_ROLES = ("TC R04", "TC R02", "System Manager")
CONFIRM_ROLES = ("TC R02", "System Manager")
TRUE_STRINGS = ("1", "true", "yes", "on")
REF = "Assembly Record"


# --- Định dạng tham số (400) -------------------------------------------------------------------------


def _string(value, name, required=True):
	if value is None and not required:
		return None
	if not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	return value


def _quantity(value):
	"""Số nguyên hoặc chuỗi số nguyên → int; giá trị khác giữ nguyên để dịch vụ báo QTY_INVALID (422)."""
	if isinstance(value, str) and value.strip().lstrip("-").isdigit():
		return int(value.strip())
	return value


def _flag(value):
	if isinstance(value, bool):
		return value
	if isinstance(value, int):
		return value != 0
	return isinstance(value, str) and value.strip().lower() in TRUE_STRINGS


# --- RPC --------------------------------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ASSEMBLY_ROLES)
@idempotent
def open(raw, station, client_ts=None, token=None):  # tên RPC theo implementation-plan §3
	"""Quét Set ID tại T3: BOM phiên bản áp dụng kèm ảnh, bản nháp kiểm đếm, cổng, cơ số (FR-M2-05, FR-M2-05.4)."""
	require_any_role(*ASSEMBLY_ROLES)
	raw = _string(raw, "raw")
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(raw)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {"ok": True, **service.open_set(raw, station, timestamp)},
		"Set Unit" if scanned["type"] == "set" else None,
		scanned["id"],
		scanned["raw"],
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ASSEMBLY_ROLES)
@idempotent
def line(
	assembly,
	station,
	instrument=None,
	raw=None,
	actual_qty=None,
	damaged_qty=None,
	replaced_qty=None,
	disposition=None,
	replacement_instrument=None,
	note=None,
	photo=None,
	all_ok=0,
	client_ts=None,
	token=None,
):
	"""Ghi một dòng kiểm đếm, quét mã dụng cụ (`raw`, FR-M1-02.2/.4) hoặc đánh dấu đủ hết (`all_ok`); xem `assembly.line`."""
	require_any_role(*ASSEMBLY_ROLES)
	name = _string(assembly, "assembly")
	instrument = _string(instrument, "instrument", required=False)
	raw = _string(raw, "raw", required=False)
	disposition = _string(disposition, "disposition", required=False)
	replacement_instrument = _string(replacement_instrument, "replacement_instrument", required=False)
	note = _string(note, "note", required=False)
	photo = _string(photo, "photo", required=False)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {
			"ok": True,
			**service.line(
				name,
				station,
				timestamp,
				instrument=instrument,
				raw=raw,
				actual_qty=_quantity(actual_qty),
				damaged_qty=_quantity(damaged_qty),
				replaced_qty=_quantity(replaced_qty),
				disposition=disposition,
				replacement_instrument=replacement_instrument,
				note=note,
				photo=photo,
				all_ok=_flag(all_ok),
			),
		},
		REF,
		name,
		gs1.parse_scan(raw)["raw"] if raw else None,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*CONFIRM_ROLES)
@idempotent
def confirm_shortage(assembly, reason, station, reviewer_proof=None, client_ts=None, token=None):
	"""R02 xác nhận đóng gói thiếu bằng PIN proof (`v1.station.verify_pin`) và lý do (FR-M2-06.1, BRU-REP-003)."""
	require_any_role(*CONFIRM_ROLES)
	name = _string(assembly, "assembly")
	reason = _string(reason, "reason")
	reviewer_proof = _string(reviewer_proof, "reviewer_proof", required=False)
	timestamp = parse_client_ts(client_ts)
	session = current_station_session()
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {
			"ok": True,
			**service.confirm_shortage(
				name, reason, station, reviewer_proof, session.name if session else None, timestamp
			),
		},
		REF,
		name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*ASSEMBLY_ROLES)
@idempotent
def submit(assembly, station, notes=None, branch=None, branch_reason=None, client_ts=None, token=None):
	"""Ghi sổ kiểm đếm và ghi cổng T3 (FR-M2-25); `branch` rẽ nhánh Sửa chữa/Thanh lý (FR-M2-00.5)."""
	require_any_role(*ASSEMBLY_ROLES)
	name = _string(assembly, "assembly")
	notes = _string(notes, "notes", required=False)
	branch = _string(branch, "branch", required=False)
	branch_reason = _string(branch_reason, "branch_reason", required=False)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {
			"ok": True,
			**service.submit(name, station, timestamp, notes, branch or None, branch_reason),
		},
		REF,
		name,
	)
