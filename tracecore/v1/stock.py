"""RPC tracecore.v1.stock.*: xuất kho thủ công theo FEFO và gợi ý lô (FEAT-042, FR-M6-04, API-M6-01, SCR-25).

``suggest_lots`` chỉ đọc; ``issue_manual`` ghi sổ nên có ``X-Idempotency-Key``. Quyền R05/R06/R09/R02/System Manager
kiểm trước mọi thao tác. Lỗi nghiệp vụ trả body ``ok: false`` (Audit Log ``Reject``), không ném.
"""

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.inventory import alerts as stock_alerts
from tracecore.inventory import consume, manual
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

ISSUE_ROLES = ("TC R05", "TC R06", "TC R09", "TC R02", "System Manager")
# FEAT-043: xem cảnh báo tồn (R06 kiểm kê, R01 xem); chỉ R09 và R02 lập đề nghị mua
ALERT_ROLES = ("TC R09", "TC R02", "TC R01", "TC R06", "System Manager")
PURCHASE_ROLES = ("TC R09", "TC R02", "System Manager")
RETRY_ROLES = ("TC R09", "TC R02", "System Manager")  # xử lý lại tiêu hao tự động bị lỗi (CONSUMPTION_FAILED)


def _lots(value):
	"""Danh sách ``[{"batch", "qty"}]`` gửi dạng JSON hoặc mảng; sai kiểu là lỗi tham số."""
	if not value:
		return None
	try:
		value = frappe.parse_json(value) if isinstance(value, str) else value
	except ValueError:
		value = None
	if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
		raise BadRequestError(_("lots must be a list of {batch, qty}."))
	return value


@frappe.whitelist(methods=["GET"])
def suggest_lots(item=None, qty=None):
	"""Gợi ý lô FEFO cho `qty` của `item`: ``{"ok", "lots", "short"}``."""
	require_any_role(*ISSUE_ROLES)
	if not item or not frappe.db.exists("Item", item):
		raise BadRequestError(_("item must be an existing item."))
	return {"ok": True, **manual.suggest(item, qty)}


@frappe.whitelist(methods=["POST"])
@idempotent
def issue_manual(item=None, qty=None, reason=None, lots=None, department=None, client_ts=None):
	"""Xuất kho thủ công; trả ``{"ok", "entry", "lots", "warnings"}`` hoặc từ chối nghiệp vụ.

	Mã từ chối: ``ISSUE_ITEM_INVALID``, ``ISSUE_QTY_INVALID``, ``REASON_REQUIRED``, ``LOT_INVALID``, ``LOT_EXPIRED``
	(422), ``STOCK_INSUFFICIENT`` (409). Cùng ``X-Idempotency-Key`` gửi lại trả đúng kết quả đã lưu.
	"""
	require_any_role(*ISSUE_ROLES)
	timestamp = parse_client_ts(client_ts)
	lots = _lots(lots)
	try:
		return {"ok": True, **manual.issue(item, qty, reason, lots, department or None)}
	except BlockedError as error:
		return reject_block(error.block, "Stock Entry", None, client_ts=timestamp)


@frappe.whitelist(methods=["GET"])
def alerts():
	"""Cảnh báo tồn (FEAT-043, FR-M6-06): ``{"ok", "below_minimum", "expiring", "unconfigured"}``; chỉ đọc."""
	require_any_role(*ALERT_ROLES)
	return {"ok": True, **stock_alerts.overview()}


@frappe.whitelist(methods=["POST"])
@idempotent
def create_purchase_request(item=None, warehouse=None, client_ts=None):
	"""Tạo đề nghị mua Nháp từ một dòng cảnh báo trong một chạm (FR-M6-06.2); đã có Nháp mở thì trả lại nó.

	Mã từ chối: ``PURCHASE_ITEM_INVALID`` (422), ``PURCHASE_NOT_NEEDED`` (409). Trả ``{"ok", "request": {...}}``.
	"""
	require_any_role(*PURCHASE_ROLES)
	timestamp = parse_client_ts(client_ts)
	try:
		doc = stock_alerts.create_purchase_request(item, warehouse)
	except BlockedError as error:
		return reject_block(error.block, "Material Request", None, client_ts=timestamp)
	line = doc.items[0]
	return {
		"ok": True,
		"request": {"name": doc.name, "item": line.item_code, "warehouse": line.warehouse, "qty": line.qty},
	}


@frappe.whitelist(methods=["POST"])
def retry_consumption(source_doctype=None, source_name=None):
	"""Chạy lại tiêu hao tự động của lô/mẻ mà lần đầu bị lỗi (nút "Retry consumption" trên form Wash Batch,
	Sterilization Load, Laundry Batch; A-78).

	Trả ``{"ok", "entry", "created", "short"}``; ``created = False`` khi lô đã có phiếu xuất (không trừ hai lần). Lỗi
	thì ném ValidationError kèm nguyên nhân.
	"""
	require_any_role(*RETRY_ROLES)
	if not (isinstance(source_doctype, str) and isinstance(source_name, str)):
		raise BadRequestError(_("source_doctype and source_name must be strings."))
	result = consume.retry(source_doctype, source_name)
	return {"ok": True, "entry": result["entry"], "created": result["created"], "short": result["short"]}
