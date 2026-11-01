"""RPC tracecore.v1.daily_test.* — màn SCR-23 test hằng ngày và khóa máy (FEAT-040, UC-23).

Lớp mỏng trên `tracecore.equipment.daily_test`, theo khuôn `v1.wash`: phiên thẻ nhân viên (`station_session`, token trong
body) → `@idempotent` → kiểm định dạng tham số (400) → gọi dịch vụ. Từ chối nghiệp vụ (`BlockedError`) thành
``{"ok": false, "error": {...}}`` kèm mã HTTP và Audit Log `Reject`. Ghi test: R05, R03 (máy rửa), R02; mở khóa tạm: chỉ R02
(FR-M5-06.1), kiểm role trước mọi ghi.
"""

import frappe

from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.equipment import daily_test
from tracecore.v1._common import current_station_session, require_any_role, station_session
from tracecore.v1.wash import _optional_str, _required_str, _run

DAILY_TEST_ROLES = ("TC R05", "TC R03", "TC R02", "System Manager")
UNLOCK_ROLES = ("TC R02",)


def _employee():
	session = current_station_session()
	return session.employee if session else None


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*DAILY_TEST_ROLES)
def overview(station, client_ts=None, token=None):
	"""Máy có test hằng ngày và tình trạng hôm nay (chỉ đọc)."""
	require_any_role(*DAILY_TEST_ROLES)
	timestamp = parse_client_ts(client_ts)
	return _run(station, timestamp, lambda: {"ok": True, "equipment": daily_test.overview()})


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*DAILY_TEST_ROLES)
@idempotent
def start_run(equipment, test_type, station, client_ts=None, token=None):
	"""Bắt đầu một lần chạy test: máy Đang test, không nạp được (A-84)."""
	require_any_role(*DAILY_TEST_ROLES)
	equipment = _required_str(equipment, "equipment")
	test_type = _required_str(test_type, "test_type")
	timestamp = parse_client_ts(client_ts)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, **daily_test.start_run(equipment, test_type, station, employee=_employee())},
		"Equipment",
		equipment,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*DAILY_TEST_ROLES)
@idempotent
def end_run(equipment, test_type, station, client_ts=None, token=None):
	"""Kết thúc lần chạy test; sau đó mới ghi được kết quả (A-84)."""
	require_any_role(*DAILY_TEST_ROLES)
	equipment = _required_str(equipment, "equipment")
	test_type = _required_str(test_type, "test_type")
	timestamp = parse_client_ts(client_ts)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, **daily_test.end_run(equipment, test_type)},
		"Equipment",
		equipment,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*DAILY_TEST_ROLES)
@idempotent
def record(
	equipment,
	test_type,
	result,
	lot,
	lot_expiry,
	station,
	photo=None,
	note=None,
	client_ts=None,
	token=None,
):
	"""Ghi một test hằng ngày: test bắt buộc Đạt mở máy, Không đạt khóa máy; máy ngoài diện chỉ lưu lại (FR-M5-05, A-70)."""
	require_any_role(*DAILY_TEST_ROLES)
	equipment = _required_str(equipment, "equipment")
	test_type = _required_str(test_type, "test_type")
	result = _required_str(result, "result")
	lot = _optional_str(lot, "lot") or ""
	lot_expiry = _optional_str(lot_expiry, "lot_expiry") or ""
	photo = _optional_str(photo, "photo")
	note = _optional_str(note, "note")
	timestamp = parse_client_ts(client_ts)
	return _run(
		station,
		timestamp,
		lambda: {
			"ok": True,
			**daily_test.record(
				equipment,
				test_type,
				result,
				station,
				lot=lot,
				lot_expiry=lot_expiry,
				photo=photo,
				employee=_employee(),
				note=note,
				client_ts=timestamp,
			),
		},
		"Equipment",
		equipment,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*UNLOCK_ROLES)
@idempotent
def unlock_temp(equipment, reason, hours, station, client_ts=None, token=None):
	"""R02 mở khóa tạm một máy: lý do và tối đa 24 giờ, Audit `Override` (FR-M5-06.1, .2)."""
	require_any_role(*UNLOCK_ROLES)
	equipment = _required_str(equipment, "equipment")
	reason = _optional_str(reason, "reason") or ""
	timestamp = parse_client_ts(client_ts)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, **daily_test.unlock_temp(equipment, reason, hours, station, timestamp)},
		"Equipment",
		equipment,
	)
