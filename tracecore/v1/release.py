"""RPC tracecore.v1.release.* — màn T5b dỡ mẻ và giải phóng (SCR-10, FEAT-023, UC-10).

Lớp mỏng trên `tracecore.reprocessing.releasing`, theo khuôn `v1.wash` (kết luận lô): phiên thẻ nhân viên
(`station_session`, token trong body) → `@idempotent` → kiểm định dạng tham số (400) → gọi dịch vụ. Từ chối nghiệp vụ
(`BlockedError`) thành ``{"ok": false, "error": {...}}`` kèm mã HTTP và Audit Log `Reject`. Trạm do dịch vụ kiểm (T5 hoặc
trạm khu cửa ra của máy, FR-M2-11.9). Giải phóng nhận `pin_proof` của R02 (`v1.station.verify_pin`) trên phiên hiện tại;
R01 giải phóng khẩn thêm `emergency_reason`.
"""

import frappe

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import releasing
from tracecore.v1._common import RELEASE_ROLES, current_station_session, require_any_role, station_session
from tracecore.v1.wash import _flag, _optional_str, _required_str, _run


def _employee():
	session = current_station_session()
	return session.employee if session else None


def _load_ref(load):
	scanned = gs1.parse_scan(load) if isinstance(load, str) else {"type": "unknown", "id": None}
	return ("Sterilization Load", scanned["id"]) if scanned["type"] == "load" else (None, None)


def _scans(load, equipment_raw, load_raw):
	return (
		_required_str(load, "load"),
		_optional_str(equipment_raw, "equipment_raw") or "",
		_optional_str(load_raw, "load_raw") or "",
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RELEASE_ROLES)
@idempotent
def context(
	load, equipment_raw, load_raw, station, entry_mode="Scan", manual_reason=None, client_ts=None, token=None
):
	"""Mở màn dỡ mẻ sau khi quét QR máy và QR mẻ: thẻ mẻ, chỉ thị đã ghi và điều kiện còn thiếu (FR-M2-11.1, .2)."""
	require_any_role(*RELEASE_ROLES)
	load, equipment_raw, load_raw = _scans(load, equipment_raw, load_raw)
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, "load": releasing.context(load, equipment_raw, load_raw, station)},
		ref_doctype,
		ref_name,
		load_raw,
		entry_mode,
		manual_reason,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RELEASE_ROLES)
@idempotent
def cycle_result(load, equipment_raw, load_raw, result, confirmed, station, client_ts=None, token=None):
	"""Ghi kết quả chu trình Đạt/Không đạt (nhập tay có xác nhận, FR-M2-11.3)."""
	require_any_role(*RELEASE_ROLES)
	load, equipment_raw, load_raw = _scans(load, equipment_raw, load_raw)
	result = _required_str(result, "result")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**releasing.set_cycle_result(
				load,
				station,
				equipment_raw,
				load_raw,
				result,
				_flag(confirmed),
				employee=_employee(),
				client_ts=timestamp,
			),
		},
		ref_doctype,
		ref_name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RELEASE_ROLES)
@idempotent
def indicator(
	load,
	equipment_raw,
	load_raw,
	indicator,
	result,
	station,
	pack=None,
	test_date=None,
	lot=None,
	incubator=None,
	client_ts=None,
	token=None,
):
	"""Ghi kết quả một chỉ thị (Bowie-Dick, hóa học 5/6, sinh học) theo mẻ hoặc theo gói (FR-M2-11)."""
	require_any_role(*RELEASE_ROLES)
	load, equipment_raw, load_raw = _scans(load, equipment_raw, load_raw)
	indicator = _required_str(indicator, "indicator")
	result = _required_str(result, "result")
	pack = _optional_str(pack, "pack")
	test_date = _optional_str(test_date, "test_date")
	lot = _optional_str(lot, "lot")
	incubator = _optional_str(incubator, "incubator")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**releasing.record_indicator(
				load,
				station,
				equipment_raw,
				load_raw,
				indicator,
				result,
				pack=pack,
				test_date=test_date,
				lot=lot,
				incubator=incubator,
				employee=_employee(),
				client_ts=timestamp,
			),
		},
		ref_doctype,
		ref_name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RELEASE_ROLES)
@idempotent
def release(
	load,
	equipment_raw,
	load_raw,
	station,
	pin_proof=None,
	review_confirmed=0,
	emergency_reason=None,
	client_ts=None,
	token=None,
):
	"""Giải phóng mẻ (R02 + PIN proof; R01 kèm lý do khẩn): Đã giải phóng hoặc Cách ly chờ BI (FR-M2-11.4, FR-M2-12)."""
	require_any_role(*RELEASE_ROLES)
	load, equipment_raw, load_raw = _scans(load, equipment_raw, load_raw)
	pin_proof = _optional_str(pin_proof, "pin_proof")
	emergency_reason = _optional_str(emergency_reason, "emergency_reason")
	timestamp = parse_client_ts(client_ts)
	session = current_station_session()
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**releasing.release(
				load,
				station,
				equipment_raw,
				load_raw,
				session=session.name if session else None,
				pin_proof=pin_proof,
				review_confirmed=_flag(review_confirmed),
				emergency_reason=emergency_reason,
				client_ts=timestamp,
			),
		},
		ref_doctype,
		ref_name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RELEASE_ROLES)
@idempotent
def reject(load, equipment_raw, load_raw, station, reason=None, redo_from="T4", client_ts=None, token=None):
	"""Mẻ Không đạt: gói hết hiệu lực, bộ về xử lý lại từ T4 (mặc định) hoặc T2 (FR-M2-12.2)."""
	require_any_role(*RELEASE_ROLES)
	load, equipment_raw, load_raw = _scans(load, equipment_raw, load_raw)
	reason = _optional_str(reason, "reason")
	redo_from = _required_str(redo_from, "redo_from")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**releasing.reject(
				load,
				station,
				equipment_raw,
				load_raw,
				reason=reason,
				redo_from=redo_from,
				employee=_employee(),
				client_ts=timestamp,
			),
		},
		ref_doctype,
		ref_name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*RELEASE_ROLES)
@idempotent
def bi_result(load, result, station, entry_mode="Scan", manual_reason=None, client_ts=None, token=None):
	"""Đọc kết quả BI của mẻ: Cách ly → giải phóng hoặc Không đạt; đã giải phóng mà dương tính → hook thu hồi (FR-M2-11.7)."""
	require_any_role(*RELEASE_ROLES)
	load = _required_str(load, "load")
	result = _required_str(result, "result")
	timestamp = parse_client_ts(client_ts)
	ref_doctype, ref_name = _load_ref(load)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**releasing.bi_result(load, result, station, employee=_employee(), client_ts=timestamp),
		},
		ref_doctype,
		ref_name,
		load,
		entry_mode,
		manual_reason,
	)
