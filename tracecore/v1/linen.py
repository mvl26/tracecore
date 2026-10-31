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
from tracecore.linen import collection, reconcile
from tracecore.linen import issue as issuing
from tracecore.v1._common import (
	LINEN_ROLES,
	BadRequestError,
	current_station_session,
	require_any_role,
	run_at_step,
	station_session,
)

FUNCTION = "LINEN"


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
		FUNCTION,
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
def balance(station, department=None, client_ts=None, token=None):
	"""Chưa trả (thu - trả - hủy), tồn khoa và định mức theo loại của `department` (UC-18 bước 2); chỉ đọc."""
	require_any_role(*LINEN_ROLES)
	department = _text(department, "department")
	timestamp = parse_client_ts(client_ts)

	def call():
		collection.check_department(department)
		return {"ok": True, "department": department, "balance": reconcile.balance(department)}

	return run_at_step(FUNCTION, station, timestamp, call)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LINEN_ROLES)
@idempotent
def issue(
	station,
	department=None,
	kind=None,
	recipient_card=None,
	sign_method=None,
	signature=None,
	lines=None,
	note=None,
	client_ts=None,
	token=None,
):
	"""Ghi sổ một lượt cấp phát: `kind` = ``Return`` hoặc ``New``, người nhận quét thẻ (`recipient_card`) và ký bằng thẻ hoặc
	cảm ứng (`signature` là ảnh PNG data URI); `lines` như `collect`. Vượt định mức tối đa chỉ cảnh báo (`quota_warning`).

	Trả ``{"ok": true, "issue": {...}}``.
	"""
	require_any_role(*LINEN_ROLES)
	department = _text(department, "department")
	kind = _text(kind, "kind")
	recipient_card = _text(recipient_card, "recipient_card")
	sign_method = _text(sign_method, "sign_method")
	signature = _text(signature, "signature")
	note = _text(note, "note")
	lines = _lines(lines)
	timestamp = parse_client_ts(client_ts)

	def call():
		doc = issuing.record(
			station, _receiver(), department, kind, recipient_card, sign_method, signature, lines, note
		)
		return {"ok": True, "issue": issuing.view(doc)}

	return run_at_step(FUNCTION, station, timestamp, call, None, None)


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

	return run_at_step(FUNCTION, station, timestamp, call, None, None)
