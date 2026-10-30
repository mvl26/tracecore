"""RPC tracecore.v1.waste.* — màn thu gom chất thải (SCR-38, FEAT-047, UC-34, FR-M10-02, A-60).

Lớp mỏng trên `tracecore.waste.collection`, theo khuôn `v1.linen`: phiên thẻ nhân viên → `@idempotent` với RPC ghi →
kiểm định dạng tham số (400) → dịch vụ. Từ chối nghiệp vụ thành ``{"ok": false, "error": {...}}`` kèm Audit `Reject`
(`_common.run_at_step`). Người thu gom là Employee của phiên thẻ; người giao và khoa lấy từ thẻ, không nhận từ tham số.
"""

import json

import frappe
from frappe import _

from tracecore.core import station_auth
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
from tracecore.waste import analysis, handover, storage, vendors
from tracecore.waste import collection as service

STEP = "WST"
RELEASE_ROLES = ("TC R02", "System Manager")
THRESHOLD_ROLES = ("TC R02", "TC R10", "System Manager")
DOCUMENT_ROLES = ("TC R07", "TC R09", "TC R02", "System Manager")


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


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
def stock(station, client_ts=None, token=None):
	"""Tồn kho chất thải, túi gấp nhất trước và nhiệt độ kho lạnh (SCR-39, FEAT-048, A-61)."""
	require_any_role(*WASTE_ROLES)
	return run_at_step(
		STEP, station, parse_client_ts(client_ts), lambda: {"ok": True, **storage.stock()}, None, None
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
def check_location(station, location=None, client_ts=None, token=None):
	"""Quét mã vị trí `KE-` (UC-35 bước 1): ``{"ok": true, "location": {name, location_name, is_cold}}``."""
	require_any_role(*WASTE_ROLES)
	location = _text(location, "location")

	def call():
		room = storage._location(location)
		return {
			"ok": True,
			"location": {"name": room.name, "location_name": room.location_name, "is_cold": room.is_cold},
		}

	return run_at_step(STEP, station, parse_client_ts(client_ts), call, None, None)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def store(station, location=None, container=None, collection=None, client_ts=None, token=None):
	"""Quét túi + vị trí (nhập kho, chuyển vị trí) hoặc quét phiếu thu gom để nhập cả phiếu (FR-M10-03, UC-35 A1, A2)."""
	require_any_role(*WASTE_ROLES)
	location = _text(location, "location")
	container = _text(container, "container")
	collection = _text(collection, "collection")

	def call():
		if collection:
			return {"ok": True, **storage.store_collection(collection)}
		doc = storage.store(container, location)
		return {
			"ok": True,
			"container": {
				"name": doc.name,
				"waste_type": doc.waste_type,
				"location": doc.storage_location,
				"storage_due": doc.storage_due,
				"cold_storage": doc.cold_storage,
			},
		}

	return run_at_step(STEP, station, parse_client_ts(client_ts), call, "Waste Container", container)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def record_temperature(station, location=None, temperature=None, client_ts=None, token=None):
	"""R07 ghi nhiệt độ kho lạnh theo ca (FR-M10-03.2, UC-35 bước 4)."""
	require_any_role(*WASTE_ROLES)
	location = _text(location, "location")

	def call():
		return {"ok": True, "log": storage.record_temperature(location, temperature).name}

	return run_at_step(STEP, station, parse_client_ts(client_ts), call, None, None)


@frappe.whitelist(methods=["GET", "POST"])
def thresholds():
	"""Ngưỡng hạn lưu và kho lạnh đang dùng (UC-35 Open issues, A-61)."""
	require_any_role(*THRESHOLD_ROLES)
	return storage.thresholds()


@frappe.whitelist(methods=["POST"])
def set_thresholds(warn_percent=None, cold_limit_c=None, breach_hours=None, variance_percent=None):
	"""R02/R10 hiệu chỉnh ngưỡng từ Desk (UC-35 Open issues, A-61)."""
	require_any_role(*THRESHOLD_ROLES)
	try:
		return {
			"ok": True,
			"thresholds": storage.set_thresholds(warn_percent, cold_limit_c, breach_hours, variance_percent),
		}
	except BlockedError as error:
		frappe.local.response["http_status_code"] = error.block.http_status
		return {"ok": False, "error": error.block.as_dict()}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
def handover_vendors(station, client_ts=None, token=None):
	"""Đơn vị xử lý chọn được và FIFO từng loại (SCR-40, FEAT-049, UC-36 bước 1, 2, A-62)."""
	require_any_role(*WASTE_ROLES)

	def call():
		rows = vendors.selectable()
		waste_types = sorted({waste_type for row in rows for waste_type in row["waste_types"]})
		return {"ok": True, "vendors": rows, "fifo": {name: handover.fifo(name) for name in waste_types}}

	return run_at_step(STEP, station, parse_client_ts(client_ts), call, None, None)


def _handover_call(station, client_ts, name, call):
	return run_at_step(
		STEP,
		station,
		parse_client_ts(client_ts),
		lambda: {"ok": True, "handover": handover.view(call())},
		"Waste Handover",
		name,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def handover_create(station, vendor=None, client_ts=None, token=None):
	"""Lập phiếu bàn giao Nháp cho đơn vị đã chọn."""
	require_any_role(*WASTE_ROLES)
	vendor = _text(vendor, "vendor")
	employee = current_station_session().employee
	return _handover_call(station, client_ts, None, lambda: handover.create(station, employee, vendor))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def handover_add(station, handover_name=None, container=None, waste_type=None, client_ts=None, token=None):
	"""Thêm một túi đã quét, hoặc cả tồn của một loại theo FIFO."""
	require_any_role(*WASTE_ROLES)
	name = _text(handover_name, "handover_name")
	container = _text(container, "container")
	waste_type = _text(waste_type, "waste_type")
	return _handover_call(
		station,
		client_ts,
		name,
		lambda: handover.add_type(name, waste_type) if waste_type else handover.add(name, container),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def handover_remove(station, handover_name=None, container=None, client_ts=None, token=None):
	"""Bỏ một túi khỏi phiếu Nháp."""
	require_any_role(*WASTE_ROLES)
	name = _text(handover_name, "handover_name")
	container = _text(container, "container")
	return _handover_call(station, client_ts, name, lambda: handover.remove(name, container))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def handover_sign(
	station, handover_name=None, weights=None, document_pending=None, values=None, client_ts=None, token=None
):
	"""Ghi kg, chứng từ và chữ ký; R07 ký bằng thẻ của phiên trạm (FR-M10-04.2, .3)."""
	require_any_role(*WASTE_ROLES)
	name = _text(handover_name, "handover_name")
	weights = _lines(weights)
	if isinstance(values, str):
		values = frappe.parse_json(values)
	if values is not None and not isinstance(values, dict):
		raise BadRequestError(_("values must be an object."))
	employee = current_station_session().employee
	fields = {key: value for key, value in (values or {}).items() if key in handover.SIGN_FIELDS}
	return _handover_call(
		station,
		client_ts,
		name,
		lambda: handover.sign(name, employee, weights=weights, document_pending=document_pending, **fields),
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*WASTE_ROLES)
@idempotent
def handover_submit(station, handover_name=None, approver_proof=None, client_ts=None, token=None):
	"""Ghi sổ phiếu; chênh lệch vượt ngưỡng cần proof của R02 từ `v1.station.verify_approver` (FR-M10-04.1)."""
	require_any_role(*WASTE_ROLES)
	name = _text(handover_name, "handover_name")
	session = current_station_session()

	def call():
		approver = None
		if approver_proof:
			approver = station_auth.consume_approver_proof(session.name, approver_proof).employee
		return handover.submit(name, approver)

	return _handover_call(station, client_ts, name, call)


@frappe.whitelist(methods=["POST"])
def attach_document(handover_name, document_no=None, scan=None, transporter=None, contract_no=None):
	"""R07/R09 đính chứng từ CTNH gửi sau từ Desk (UC-36 A4)."""
	require_any_role(*DOCUMENT_ROLES)
	try:
		doc = handover.attach_document(handover_name, document_no, scan, transporter, contract_no)
	except BlockedError as error:
		frappe.local.response["http_status_code"] = error.block.http_status
		return {"ok": False, "error": error.block.as_dict()}
	return {"ok": True, "document_pending": doc.document_pending}


@frappe.whitelist(methods=["GET", "POST"])
def my_department(from_date, to_date):
	"""R08 xem kg và NC phân loại sai của đúng khoa mình (FR-M10-07.3, NFR-SEC-07); chưa có Portal nên chỉ là RPC (A-63)."""
	require_any_role("TC R08", "TC R01", "TC R02", "System Manager")
	department = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "department")
	if not department:
		return {"rows": [], "misclassifications": []}
	return analysis.department_summary(department, from_date, to_date)


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
