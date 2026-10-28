"""RPC tracecore.v1.stock.*: xuất kho thủ công theo FEFO và gợi ý lô (FEAT-042, FR-M6-04, API-M6-01, SCR-25).

``suggest_lots`` chỉ đọc; ``issue_manual`` ghi sổ nên có ``X-Idempotency-Key``. Quyền R05/R06/R09/R02/System Manager
kiểm trước mọi thao tác. Lỗi nghiệp vụ trả body ``ok: false`` (Audit Log ``Reject``), không ném.
"""

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.inventory import manual
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

ISSUE_ROLES = ("TC R05", "TC R06", "TC R09", "TC R02", "System Manager")


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
