"""RPC tracecore.v1.waste.* — màn thu gom chất thải (SCR-38, FEAT-047, UC-34, FR-M10-02, A-60).

Lớp mỏng trên `tracecore.waste.collection`, theo khuôn `v1.linen`: phiên thẻ nhân viên → `@idempotent` với RPC ghi →
kiểm định dạng tham số (400) → dịch vụ. Từ chối nghiệp vụ thành ``{"ok": false, "error": {...}}`` kèm Audit `Reject`
(`_common.run_at_step`). Người thu gom là Employee của phiên thẻ; người giao và khoa lấy từ thẻ, không nhận từ tham số.
"""

import json

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import (
	WASTE_ROLES,
	BadRequestError,
	current_station_session,
	require_any_role,
	run_at_step,
	station_session,
)
from tracecore.waste import collection as service

STEP = "WST"
RELEASE_ROLES = ("TC R02", "System Manager")


def _text(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	return value or None


def _lines(value):
	"""`lines` là list (hoặc chuỗi JSON của list) các object; không có → None (dịch vụ trả WASTE_EMPTY)."""
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


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
def catalog(station, client_ts=None, token=None):
	"""Loại chất thải đang dùng: ``{"ok": true, "types": [...]}``."""
	require_any_role(*WASTE_ROLES)
	return run_at_step(
		STEP,
		station,
		parse_client_ts(client_ts),
		lambda: {"ok": True, "types": service.catalog()},
		None,
		None,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
def giver(station, card=None, client_ts=None, token=None):
	"""Quét thẻ người giao (UC-34 bước 1): ``{"ok": true, "giver": {employee, employee_name, department}}``."""
	require_any_role(*WASTE_ROLES)
	card = _text(card, "card")
	return run_at_step(
		STEP,
		station,
		parse_client_ts(client_ts),
		lambda: {"ok": True, "giver": service.giver(card)},
		None,
		None,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def collect(station, card=None, lines=None, total_kg=None, note=None, client_ts=None, token=None):
	"""Ghi sổ một lượt thu gom: `lines` = ``[{"waste_type", "qty", "weight_kg", "weight_source", "weight_confirmed",
	"misclassified", "misclass_note"}]``; `total_kg` chia cân tổng của xe (UC-34 A2).

	Trả ``{"ok": true, "collection": {...}}``.
	"""
	require_any_role(*WASTE_ROLES)
	card = _text(card, "card")
	note = _text(note, "note")
	lines = _lines(lines)
	employee = current_station_session().employee

	def call():
		doc = service.record(station, employee, card, lines, total_kg, note)
		return {"ok": True, "collection": service.view(doc)}

	return run_at_step(STEP, station, parse_client_ts(client_ts), call, None, None)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def acknowledge(station, collection=None, card=None, client_ts=None, token=None):
	"""Biên nhận với khoa: người giao hoặc đồng nghiệp cùng khoa quét lại thẻ (A-60 W4)."""
	require_any_role(*WASTE_ROLES)
	collection = _text(collection, "collection")
	card = _text(card, "card")

	def call():
		doc = service.acknowledge(collection, card)
		return {"ok": True, "acknowledged_by": doc.acknowledged_by}

	return run_at_step(STEP, station, parse_client_ts(client_ts), call, "Waste Collection", collection)


@frappe.whitelist(methods=["POST"])
def release_held(container, note=None):
	"""R02 mở túi bị giữ vì phân loại sai, từ Desk (FR-M10-02.4, A-60 W12)."""
	require_any_role(*RELEASE_ROLES)
	try:
		service.release_held(container, note, frappe.session.user)
	except BlockedError as error:
		frappe.local.response["http_status_code"] = error.block.http_status
		return {"ok": False, "error": error.block.as_dict()}
	return {"ok": True}
