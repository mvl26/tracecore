"""RPC tracecore.v1.wash.* — màn T2 lô rửa (SCR-06, FEAT-021): quét máy, nạp bộ, Hoàn thành nạp, dỡ lô, kết luận.

Lớp mỏng trên `tracecore.reprocessing.washing`, theo khuôn `v1.pack`: phiên thẻ nhân viên (`station_session`, token
trong body) → `@idempotent` → kiểm định dạng tham số (400) → gọi dịch vụ. Từ chối nghiệp vụ (`BlockedError`) thành
``{"ok": false, "error": {...}}`` kèm mã HTTP và Audit Log `Reject`, không ném lại. Nạp lô chỉ ở trạm bước T2
(`run_at_step`); dỡ, nhập dữ liệu và kết luận ở trạm T2 hoặc trạm khu cửa ra của máy (Q5, dịch vụ kiểm).
BA: ``cssd.wash.create_batch`` ↔ `complete`, ``cssd.wash.set_result`` ↔ `result` (A-12).
"""

import json

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import washing
from tracecore.v1._common import (
	WASH_LOAD_ROLES,
	WASH_UNLOAD_ROLES,
	BadRequestError,
	current_station_session,
	reject_block,
	require_any_role,
	run_at_step,
	station_session,
)

FUNCTION = washing.FUNCTION
TRUE_STRINGS = ("1", "true", "yes", "on")


# --- Định dạng tham số (400) -------------------------------------------------------------------------


def _json_list(value, message):
	"""`value` là list hoặc chuỗi JSON của một list (form-encoded gửi list dạng chuỗi); ngược lại 400."""
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			raise BadRequestError(message) from None
	if not isinstance(value, list):
		raise BadRequestError(message)
	return value


def _codes(value, name):
	message = _("{0} must be a list of scanned codes.").format(name)
	codes = _json_list(value, message)
	if not all(isinstance(code, str) for code in codes):
		raise BadRequestError(message)
	return codes


def _chemicals(value):
	message = _("chemicals must be a list of objects with an item and a lot.")
	rows = []
	for row in _json_list(value, message):
		if not (
			isinstance(row, dict) and isinstance(row.get("item"), str) and isinstance(row.get("lot"), str)
		):
			raise BadRequestError(message)
		if row.get("qty") is not None and not isinstance(row["qty"], int | float):
			raise BadRequestError(message)
		rows.append({"item": row["item"], "lot": row["lot"], "qty": row.get("qty")})
	return rows


def _values(value):
	message = _("values must be a list of objects with a parameter_name and a value.")
	rows = []
	for row in _json_list(value, message):
		if not (isinstance(row, dict) and isinstance(row.get("parameter_name"), str)):
			raise BadRequestError(message)
		if row.get("value") is not None and not isinstance(row["value"], str | int | float):
			raise BadRequestError(message)
		rows.append({"parameter_name": row["parameter_name"], "value": row.get("value")})
	return rows


def _optional_str(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	return value or None


def _required_str(value, name):
	if not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	return value


def _flag(value):
	if isinstance(value, bool):
		return value
	if isinstance(value, int):
		return value != 0
	if isinstance(value, str):
		return value.strip().lower() in TRUE_STRINGS
	return False


def _session_employee():
	session = current_station_session()
	return session.employee if session else None


def _run(station, timestamp, call, ref_doctype=None, ref_name=None, raw=None):
	"""Như `run_at_step` cho thao tác dỡ lô: trạm do dịch vụ kiểm (T2 hoặc cửa ra, Q5)."""
	try:
		return call()
	except BlockedError as error:
		return reject_block(
			error.block,
			ref_doctype,
			ref_name,
			raw,
			station=station if isinstance(station, str) else None,
			client_ts=timestamp,
		)


def _batch_ref(batch):
	scanned = gs1.parse_scan(batch) if isinstance(batch, str) else {"type": "unknown", "id": None}
	return ("Wash Batch", scanned["id"]) if scanned["type"] == "wash_batch" else (None, None)


# --- Nạp lô (trạm T2) -------------------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_LOAD_ROLES)
@idempotent
def start(raw, station, entry_mode="Scan", manual_reason=None, client_ts=None, token=None):
	"""Quét QR máy rửa: máy, chương trình đang dùng của máy, lô hóa chất gợi ý FEFO (FR-M2-03.1, .4, .5)."""
	require_any_role(*WASH_LOAD_ROLES)
	raw = _required_str(raw, "raw")
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(raw)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {"ok": True, **washing.scan_machine(raw)},
		"Equipment" if scanned["type"] == "equipment" else None,
		scanned["id"],
		scanned["raw"],
		entry_mode,
		manual_reason,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_LOAD_ROLES)
@idempotent
def add_set(
	raw, equipment, queued, station, entry_mode="Scan", manual_reason=None, client_ts=None, token=None
):
	"""Kiểm một Set ID quét vào máy `equipment` (không ghi); `queued` là danh sách đang quét trên kiosk (Q1)."""
	require_any_role(*WASH_LOAD_ROLES)
	raw = _required_str(raw, "raw")
	equipment = _required_str(equipment, "equipment")
	queue = _codes(queued, "queued")
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(raw)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {"ok": True, **washing.admit_set(raw, equipment, queue)},
		"Set Unit" if scanned["type"] == "set" else None,
		scanned["id"],
		scanned["raw"],
		entry_mode,
		manual_reason,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_LOAD_ROLES)
@idempotent
def complete(equipment, program, sets, chemicals, station, client_ts=None, token=None):
	"""Hoàn thành nạp: sinh mã lô `LR-`, gắn bộ, in nhãn QR (FR-M2-03.2, FR-M2-24.1); trả cả bộ bị loại (Q19)."""
	require_any_role(*WASH_LOAD_ROLES)
	equipment = _required_str(equipment, "equipment")
	program = _required_str(program, "program")
	codes = _codes(sets, "sets")
	rows = _chemicals(chemicals)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {
			"ok": True,
			**washing.start(equipment, program, codes, rows, station, timestamp, _session_employee()),
		},
		"Equipment",
		equipment,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_LOAD_ROLES)
def redo_queue(station, client_ts=None, token=None):
	"""Bảng phụ của màn T2, chỉ đọc: hàng đợi xử lý lại (``sets``, FR-M2-25.2, Q16), lô đang chạy (``running``) và bộ chờ rửa
	(``waiting``, A-66)."""
	require_any_role(*WASH_LOAD_ROLES)
	parse_client_ts(client_ts)
	return run_at_step(
		washing.LOAD_OR_UNLOAD,
		station,
		None,
		lambda: {
			"ok": True,
			"sets": washing.redo_queue(),
			"running": washing.running_batches(),
			"waiting": washing.waiting_sets(),
		},
	)


# --- Tra cứu, dỡ lô, dữ liệu, kết luận ---------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_UNLOAD_ROLES)
def lookup(raw, station, client_ts=None, token=None):
	"""Thẻ tra cứu lô rửa từ mã `LR-` (FR-M2-03.3); chỉ đọc, mở ở mọi trạm."""
	require_any_role(*WASH_UNLOAD_ROLES)
	raw = _required_str(raw, "raw")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _batch_ref(raw)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, "batch": washing.lookup(raw)},
		ref_doctype,
		ref_name,
		gs1.parse_scan(raw)["raw"],
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_UNLOAD_ROLES)
@idempotent
def unload(batch, raw, station, client_ts=None, token=None):
	"""Kiểm một mã quét khi dỡ lô `batch`: QR máy của lô hoặc QR lô (Q15, FR-M2-04.1/.2)."""
	require_any_role(*WASH_UNLOAD_ROLES)
	batch = _required_str(batch, "batch")
	raw = _required_str(raw, "raw")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _batch_ref(batch)
	return _run(
		station,
		timestamp,
		lambda: washing.scan_unload(batch, raw, station),
		ref_doctype,
		ref_name,
		gs1.parse_scan(raw)["raw"],
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_UNLOAD_ROLES)
@idempotent
def unload_context(batch, equipment_raw, batch_raw, station, client_ts=None, token=None):
	"""Ngữ cảnh dỡ lô sau khi đã quét đủ hai mã: thẻ lô + `parameter_schema` của chương trình."""
	require_any_role(*WASH_UNLOAD_ROLES)
	batch = _required_str(batch, "batch")
	equipment_raw = _optional_str(equipment_raw, "equipment_raw") or ""
	batch_raw = _optional_str(batch_raw, "batch_raw") or ""
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _batch_ref(batch)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, "batch": washing.unload_context(batch, equipment_raw, batch_raw, station)},
		ref_doctype,
		ref_name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_UNLOAD_ROLES)
@idempotent
def manual_data(
	batch,
	equipment_raw,
	batch_raw,
	values,
	started_at,
	ended_at,
	confirmed,
	station,
	reported_result=None,
	machine_alerts=None,
	machine_file=None,
	client_ts=None,
	token=None,
):
	"""Lưu dữ liệu chu trình nhập tay có xác nhận của người đang đăng nhập thẻ (FR-M2-24.3/.5, BRU-REP-015)."""
	require_any_role(*WASH_UNLOAD_ROLES)
	batch = _required_str(batch, "batch")
	rows = _values(values)
	equipment_raw = _optional_str(equipment_raw, "equipment_raw") or ""
	batch_raw = _optional_str(batch_raw, "batch_raw") or ""
	started_at = _optional_str(started_at, "started_at")
	ended_at = _optional_str(ended_at, "ended_at")
	reported_result = _optional_str(reported_result, "reported_result")
	machine_alerts = _optional_str(machine_alerts, "machine_alerts")
	machine_file = _optional_str(machine_file, "machine_file")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _batch_ref(batch)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**washing.save_manual_data(
				batch,
				equipment_raw,
				batch_raw,
				rows,
				reported_result,
				started_at,
				ended_at,
				machine_alerts,
				machine_file,
				_flag(confirmed),
				timestamp,
				employee=_session_employee(),
				station=station,
			),
		},
		ref_doctype,
		ref_name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASH_UNLOAD_ROLES)
@idempotent
def result(
	batch,
	result,
	equipment_raw,
	batch_raw,
	clean_test,
	station,
	reviewer_proof=None,
	note=None,
	client_ts=None,
	token=None,
):
	"""Kết luận lô: một kết quả Đạt/Không đạt cho mọi bộ, đóng lô (FR-M2-04.3 đến .6, BRU-REP-002); xem `washing.set_result`.

	`reviewer_proof` là PIN proof (`v1.station.verify_pin`) của R02 trên phiên này, cần cho Đạt ở máy cũ (Q7).
	"""
	require_any_role(*WASH_UNLOAD_ROLES)
	batch = _required_str(batch, "batch")
	result = _required_str(result, "result")
	clean_test = _required_str(clean_test, "clean_test")
	equipment_raw = _optional_str(equipment_raw, "equipment_raw") or ""
	batch_raw = _optional_str(batch_raw, "batch_raw") or ""
	reviewer_proof = _optional_str(reviewer_proof, "reviewer_proof")
	note = _optional_str(note, "note")
	timestamp = parse_client_ts(client_ts)
	session = current_station_session()
	ref_doctype, ref_name = _batch_ref(batch)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**washing.set_result(
				batch,
				result,
				station,
				equipment_raw,
				batch_raw,
				clean_test,
				reviewer_proof=reviewer_proof,
				note=note,
				client_ts=timestamp,
				session=session.name if session else None,
			),
		},
		ref_doctype,
		ref_name,
	)
