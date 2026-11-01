"""RPC tracecore.v1.load.* — màn T5 nạp mẻ tiệt khuẩn (SCR-09 STN, SCR-35 PDA, FEAT-022): quét máy, nạp gói, Hoàn thành nạp, dữ liệu.

Lớp mỏng trên `tracecore.reprocessing.sterilizing`, theo khuôn `v1.wash`: phiên thẻ nhân viên (`station_session`, token
trong body) → `@idempotent` → kiểm định dạng tham số (400) → gọi dịch vụ. Từ chối nghiệp vụ (`BlockedError`) thành
``{"ok": false, "error": {...}}`` kèm mã HTTP và Audit Log `Reject`, không ném lại. Nạp mẻ chỉ ở trạm bước T5
(`run_at_step`); nhập dữ liệu chu trình ở trạm T5 hoặc trạm khu cửa ra của máy (dịch vụ kiểm).
BA: ``cssd.load.create`` ↔ `complete` (`create` = quét QR máy mở phiên nạp), ``cssd.load.add_pack`` ↔ `add_pack` (A-16).
"""

import frappe

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import machine_data, sterilizing
from tracecore.v1._common import (
	LOAD_ROLES,
	current_station_session,
	require_agent_for,
	require_any_role,
	require_station,
	run_at_step,
	station_session,
)
from tracecore.v1.wash import _codes, _flag, _optional_str, _required_str, _run, _values

FUNCTION = sterilizing.FUNCTION


def _session_employee():
	session = current_station_session()
	return session.employee if session else None


def _load_ref(load):
	scanned = gs1.parse_scan(load) if isinstance(load, str) else {"type": "unknown", "id": None}
	return ("Sterilization Load", scanned["id"]) if scanned["type"] == "load" else (None, None)


# --- Nạp mẻ (trạm T5) ----------------------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
@idempotent
def create(raw, station, entry_mode="Scan", manual_reason=None, client_ts=None, token=None):
	"""Quét QR máy tiệt khuẩn: máy, chương trình đang dùng của máy, chỉ thị theo chương trình (FR-M2-09.1, .3)."""
	require_any_role(*LOAD_ROLES)
	raw = _required_str(raw, "raw")
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(raw)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {"ok": True, **sterilizing.scan_machine(raw)},
		"Equipment" if scanned["type"] == "equipment" else None,
		scanned["id"],
		scanned["raw"],
		entry_mode,
		manual_reason,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
@idempotent
def add_pack(
	raw,
	equipment,
	program,
	queued,
	station,
	entry_mode="Scan",
	manual_reason=None,
	client_ts=None,
	token=None,
):
	"""Kiểm một Cycle ID quét vào máy `equipment` (không ghi); `queued` là danh sách đang quét trên kiosk (A-16, Q1)."""
	require_any_role(*LOAD_ROLES)
	raw = _required_str(raw, "raw")
	equipment = _required_str(equipment, "equipment")
	program = _required_str(program, "program")
	queue = _codes(queued, "queued")
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(raw)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {"ok": True, **sterilizing.admit_pack(raw, equipment, program, queue)},
		"Pack" if scanned["type"] == "pack" else None,
		scanned["id"],
		scanned["raw"],
		entry_mode,
		manual_reason,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
def recheck(equipment, program, packs, station, client_ts=None, token=None):
	"""Kiểm lại danh sách gói đang nạp theo chương trình mới (A-88); chỉ đọc nên không ghi Audit Log từ chối."""
	require_any_role(*LOAD_ROLES)
	equipment = _required_str(equipment, "equipment")
	program = _required_str(program, "program")
	codes = _codes(packs, "packs")
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {"ok": True, "packs": sterilizing.recheck_packs(equipment, program, codes)},
		"Equipment",
		equipment,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
@idempotent
def complete(equipment, program, packs, station, is_priority=0, client_ts=None, token=None):
	"""Hoàn thành nạp: sinh mã mẻ `ME-`, gắn gói, in nhãn QR (FR-M2-09, FR-M2-24.1); trả cả gói bị loại."""
	require_any_role(*LOAD_ROLES)
	equipment = _required_str(equipment, "equipment")
	program = _required_str(program, "program")
	codes = _codes(packs, "packs")
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {
			"ok": True,
			**sterilizing.complete(
				equipment, program, codes, station, timestamp, _session_employee(), _flag(is_priority)
			),
		},
		"Equipment",
		equipment,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
def overview(station, client_ts=None, token=None):
	"""Bảng phụ của màn T5, chỉ đọc: mẻ đang chạy / đã có dữ liệu chưa dỡ (``running``)."""
	require_any_role(*LOAD_ROLES)
	parse_client_ts(client_ts)
	return run_at_step(
		sterilizing.LOAD_OR_UNLOAD,
		station,
		None,
		lambda: {"ok": True, "running": sterilizing.running_loads()},
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
def label_pdf(load, station, client_ts=None, token=None):
	"""PDF nhãn QR của mẻ, máy trạm tự lưu thành file (A-99); chỉ đọc, chạy được khi không có máy in."""
	require_any_role(*LOAD_ROLES)
	load = _required_str(load, "load")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return run_at_step(
		FUNCTION,
		station,
		timestamp,
		lambda: {"ok": True, **sterilizing.label_pdf(load)},
		ref_doctype,
		ref_name,
		load,
	)


# --- Tra cứu, dữ liệu chu trình --------------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
def lookup(raw, station, client_ts=None, token=None):
	"""Thẻ tra cứu mẻ từ mã `ME-` (FR-M2-09.2); chỉ đọc, mở ở mọi trạm."""
	require_any_role(*LOAD_ROLES)
	raw = _required_str(raw, "raw")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(raw)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, "load": sterilizing.lookup(raw)},
		ref_doctype,
		ref_name,
		gs1.parse_scan(raw)["raw"],
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
@idempotent
def data_scan(load, raw, station, entry_mode="Scan", manual_reason=None, client_ts=None, token=None):
	"""Kiểm một mã quét khi nhập dữ liệu mẻ `load`: QR máy của mẻ hoặc QR mẻ (A-16, Q10)."""
	require_any_role(*LOAD_ROLES)
	load = _required_str(load, "load")
	raw = _required_str(raw, "raw")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: sterilizing.scan_for_data(load, raw, station),
		ref_doctype,
		ref_name,
		gs1.parse_scan(raw)["raw"],
		entry_mode,
		manual_reason,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
@idempotent
def data_context(load, equipment_raw, load_raw, station, client_ts=None, token=None):
	"""Ngữ cảnh nhập dữ liệu sau khi đã quét đủ hai mã: thẻ mẻ + `parameter_schema` của chương trình."""
	require_any_role(*LOAD_ROLES)
	load = _required_str(load, "load")
	equipment_raw = _optional_str(equipment_raw, "equipment_raw") or ""
	load_raw = _optional_str(load_raw, "load_raw") or ""
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, "load": sterilizing.data_context(load, equipment_raw, load_raw, station)},
		ref_doctype,
		ref_name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LOAD_ROLES)
@idempotent
def manual_data(
	load,
	equipment_raw,
	load_raw,
	values,
	started_at,
	ended_at,
	confirmed,
	card,
	station,
	machine_alerts=None,
	machine_report=None,
	reason=None,
	client_ts=None,
	token=None,
):
	"""Lưu dữ liệu chu trình nhập tay có xác nhận thẻ của người đang đăng nhập (FR-M2-10, BRU-REP-015)."""
	require_any_role(*LOAD_ROLES)
	load = _required_str(load, "load")
	rows = _values(values)
	equipment_raw = _optional_str(equipment_raw, "equipment_raw") or ""
	load_raw = _optional_str(load_raw, "load_raw") or ""
	started_at = _optional_str(started_at, "started_at")
	ended_at = _optional_str(ended_at, "ended_at")
	card = _optional_str(card, "card") or ""
	machine_alerts = _optional_str(machine_alerts, "machine_alerts")
	machine_report = _optional_str(machine_report, "machine_report")
	reason = _optional_str(reason, "reason")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**sterilizing.save_manual_data(
				load,
				equipment_raw,
				load_raw,
				rows,
				started_at,
				ended_at,
				machine_alerts,
				machine_report,
				reason,
				_flag(confirmed),
				card,
				timestamp,
				employee=_session_employee(),
				station=station,
			),
		},
		ref_doctype,
		ref_name,
	)


# --- Dữ liệu máy tự động qua station agent (FEAT-024, A-39, ADR-007) -----------------------------------------


@frappe.whitelist(methods=["POST"])
@idempotent
def ingest_machine_data(station, equipment, cycle, client_ts=None):
	"""Agent của trạm gửi một chu trình máy rửa / máy tiệt khuẩn (FR-M2-24, EI-SW-001); dùng chung cho cả hai loại máy.

	`cycle` (JSON) = ``{cycle_ref, load_id, program, started_at, ended_at, parameters[{parameter_name, value}], alerts,
	result, driver}``. Chỉ user agent của đúng `station` (role TC Agent, API key); chặn nghiệp vụ trả ``ok: false``
	(chưa khớp → MACHINE_CYCLE_UNMATCHED 404, agent gửi lại sau).
	"""
	require_agent_for(station)
	require_station(station)
	timestamp = parse_client_ts(client_ts) if client_ts else None
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, **machine_data.ingest(station, equipment, cycle)},
		"Equipment",
		equipment if isinstance(equipment, str) else None,
	)
