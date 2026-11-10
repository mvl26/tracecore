"""RPC tracecore.v1.isolation.* — SCR-60 Lệnh cách ly & phòng cách ly (FEAT-068; FR-M14-06, .1, FR-M14-07; UC-52;
BRU-MDR-003; A-146).

- ``overview`` (GET): màn WEB trong Page `tc-ksnk` (slug ``cach-ly``) — form tạo lệnh (điền sẵn từ chủng ``isolate``),
  danh sách đang cách ly mọi khoa, phòng cách ly theo khoa, tỷ lệ khoa lâm sàng có ≥ 1 phòng đạt + khoa chưa có. R13 chỉ
  nhận phòng và tỷ lệ (không đọc DocType có người bệnh, ADR-010).
- ``portal_context`` (GET): Cổng khoa `/ksnk-khoa/cach-ly` — R08/R12 chỉ khoa có User Permission Department.
- ``create_order``, ``close_order``, ``cancel_order`` (POST, ``@idempotent``): lỗi nghiệp vụ trả body
  ``{ok: false, error: {code, title, reason, action}}`` để màn hiện ``alert-error`` inline. Mã BN không bao giờ trả về
  dạng rõ (chỉ ``patient_code_masked``).
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.microbiology import isolation, permissions
from tracecore.ui import ksnk
from tracecore.v1._common import reject_block, require_any_role

SCREEN_SLUG = "cach-ly"
WRITE_ROLES = ("TC R01", "TC R08", "TC R11", "TC R12", "System Manager")
ORDER_KEYS = (
	"name",
	"patient_code_masked",
	"department",
	"department_name",
	"isolation_room",
	"bedside_isolation",
	"precaution_type",
	"reason",
	"reason_detail",
	"isolate",
	"is_mdro",
	"start_at",
	"end_at",
	"end_reason",
	"status",
)


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == SCREEN_SLUG)
	if not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(_("You are not allowed to open the isolation screen."), frappe.PermissionError)


def _require_portal():
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Sign in to record isolation orders."))
	require_any_role(*WRITE_ROLES)


def _can_write():
	return bool(set(frappe.get_roles()) & set(WRITE_ROLES)) and bool(
		frappe.has_permission(isolation.DOCTYPE, "create")
	)


def _choices():
	return {
		"precautions": list(isolation.PRECAUTIONS),
		"reasons": list(isolation.REASONS),
		"mdro_reason": isolation.REASON_MDRO,
		"mdro_close": isolation.can_close_mdro(),
		"can_cancel": frappe.session.user == "Administrator"
		or bool(set(frappe.get_roles()) & set(isolation.CANCEL_ROLES)),
	}


def _departments(allowed):
	"""Khoa chọn được trên form: R08/R12 theo User Permission; vai trò rộng → khoa lâm sàng."""
	if allowed is None:
		rows = isolation.clinical_departments()
	else:
		rows = frappe.get_all(
			"Department",
			filters={"name": ["in", allowed or [""]], "disabled": 0},
			fields=["name", "department_name"],
			order_by="department_name asc",
		)
	return [{"name": row.name, "label": row.department_name or row.name} for row in rows]


def _prefill(isolate, allowed):
	if not isolate:
		return None
	data = isolation.prefill(isolate)
	if allowed is not None and data["department"] not in allowed:
		return None
	return data


def _order(doc):
	return {key: doc.get(key) for key in ORDER_KEYS}


@frappe.whitelist(methods=["GET"])
def overview(department=None, isolate=None):
	"""Dữ liệu SCR-60 WEB (chỉ đọc)."""
	_require_screen()
	can_read_orders = bool(frappe.has_permission(isolation.DOCTYPE, "read"))
	departments = [department] if department else None
	result = {
		"ok": True,
		"can_write": _can_write(),
		"can_read_orders": can_read_orders,
		"departments": _departments(None),
		"orders": isolation.open_orders(departments) if can_read_orders else [],
		"rooms": isolation.rooms(departments),
		"coverage": isolation.coverage(department=department),
		"prefill": _prefill(isolate, None) if can_read_orders and isolate else None,
		"room_form": "/app/isolation-room/new",
		"can_edit_rooms": bool(frappe.has_permission(isolation.ROOM_DOCTYPE, "write")),
		**_choices(),
	}
	return result


@frappe.whitelist(methods=["GET"])
def portal_context(isolate=None):
	"""Dữ liệu Cổng khoa `/ksnk-khoa/cach-ly` (SCR-60 DEPT)."""
	_require_portal()
	allowed = permissions.allowed_departments()
	departments = _departments(allowed)
	names = [row["name"] for row in departments]
	scope = names if allowed is not None else None
	return {
		"ok": True,
		"departments": departments,
		"orders": isolation.open_orders(scope),
		"rooms": isolation.rooms(scope),
		"prefill": _prefill(isolate, allowed),
		**_choices(),
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def create_order(
	department=None,
	patient_code=None,
	isolate=None,
	isolation_room=None,
	precaution_type=None,
	reason=None,
	reason_detail=None,
	start_at=None,
	client_ts=None,
):
	"""Tạo và ghi sổ lệnh cách ly: ``{ok, order, warnings}``."""
	require_any_role(*WRITE_ROLES)
	timestamp = parse_client_ts(client_ts)
	values = {
		"department": department or None,
		"patient_code": patient_code,
		"isolate": isolate or None,
		"isolation_room": isolation_room or None,
		"precaution_type": precaution_type,
		"reason": reason,
		"reason_detail": reason_detail,
		"start_at": (start_at or "").replace("T", " ") or None,
	}
	try:
		doc = isolation.create_order(values)
	except BlockedError as error:
		return reject_block(error.block, isolation.DOCTYPE, isolate or department, client_ts=timestamp)
	return {"ok": True, "order": _order(doc), "warnings": doc.flags.tc_warnings or []}


@frappe.whitelist(methods=["POST"])
@idempotent
def close_order(order=None, end_reason=None, end_at=None, client_ts=None):
	"""Kết thúc lệnh cách ly có lý do (BRU-MDR-003): ``{ok, order}``."""
	require_any_role(*WRITE_ROLES)
	timestamp = parse_client_ts(client_ts)
	try:
		doc = isolation.close_order(order, end_reason, (end_at or "").replace("T", " ") or None)
	except BlockedError as error:
		return reject_block(error.block, isolation.DOCTYPE, order, client_ts=timestamp)
	return {"ok": True, "order": _order(doc)}


@frappe.whitelist(methods=["POST"])
@idempotent
def cancel_order(order=None, reason=None, client_ts=None):
	"""Hủy lệnh nhập nhầm (R01/R11): ``{ok, order}``."""
	timestamp = parse_client_ts(client_ts)
	try:
		doc = isolation.cancel_order(order, reason)
	except BlockedError as error:
		return reject_block(error.block, isolation.DOCTYPE, order, client_ts=timestamp)
	return {"ok": True, "order": _order(doc), "cancelled": cint(doc.docstatus) == 2}
