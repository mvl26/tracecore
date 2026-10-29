"""RPC tracecore.v1.linen.* — màn thu gom đồ vải (SCR-16, FEAT-033, UC-16, FR-M3-01).

Lớp mỏng trên `tracecore.linen.collection`, theo khuôn `v1.receive`: phiên thẻ nhân viên (`station_session`, token trong
body) → `@idempotent` → kiểm định dạng tham số (400) → gọi dịch vụ. Từ chối nghiệp vụ (`BlockedError`) thành
``{"ok": false, "error": {...}}`` (xem `_common.run_at_step`). Mọi RPC chỉ chạy ở trạm bước LIN (trạm đồ vải, A-49 L1);
người nhận là Employee của phiên thẻ, không nhận từ tham số.
"""

import json

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.linen import collection
from tracecore.v1._common import (
	LINEN_ROLES,
	BadRequestError,
	current_station_session,
	require_any_role,
	run_at_step,
	station_session,
)

STEP = "LIN"


def _text(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	return value or None


def _lines(value):
	"""`lines` là list (hoặc chuỗi JSON của list) các object; không có → None (dịch vụ trả LINEN_EMPTY)."""
	if value is None:
		return None
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			raise BadRequestError(_("lines must be a list of objects.")) from None
	if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
		raise BadRequestError(_("lines must be a list of objects."))
	return value


def _receiver():
	session = current_station_session()
	return session.employee if session else None


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LINEN_ROLES)
def catalog(station, department=None, client_ts=None, token=None):
	"""Loại đồ vải đang dùng (kèm định mức của `department`) và các khoa chọn được; chỉ đọc, không ghi Idempotency Key."""
	require_any_role(*LINEN_ROLES)
	department = _text(department, "department")
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {
			"ok": True,
			"types": collection.catalog(department),
			"departments": collection.departments(),
		},
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LINEN_ROLES)
@idempotent
def collect(
	station,
	department=None,
	delivered_by=None,
	lines=None,
	total_kg=None,
	note=None,
	client_ts=None,
	token=None,
):
	"""Ghi sổ một lượt thu gom: `lines` = ``[{"linen_type", "qty", "weight_kg", "contaminated", "weight_source",
	"variance_note"}]`` (thiếu qty hoặc weight_kg thì quy đổi); `total_kg` chia cân tổng của xe cho các dòng (UC-16 A1).

	Trả ``{"ok": true, "collection": {...}}``.
	"""
	require_any_role(*LINEN_ROLES)
	department = _text(department, "department")
	delivered_by = _text(delivered_by, "delivered_by")
	note = _text(note, "note")
	lines = _lines(lines)
	timestamp = parse_client_ts(client_ts)

	def call():
		doc = collection.record(station, _receiver(), department, delivered_by, lines, total_kg, note)
		return {"ok": True, "collection": collection.view(doc)}

	return run_at_step(STEP, station, timestamp, call, None, None)
