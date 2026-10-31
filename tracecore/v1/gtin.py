"""RPC tracecore.v1.gtin.*: trạng thái mã doanh nghiệp GS1, cấp bù GTIN-14, đổi GTIN đã khóa (A-76).

Ghi: POST + ``@idempotent`` (``X-Idempotency-Key``, ``client_ts`` ISO 8601 có offset), chỉ TC R10. Từ chối nghiệp vụ:
body ``{"ok": false, "error"}`` + mã HTTP + Audit Log ``Reject``. Nghiệp vụ ở ``tracecore.instrument.gtin``.
"""

import frappe
from frappe import _

from tracecore.core import code_registry, gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.instrument import gtin as gtin_rules
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

ADMIN_ROLE = gtin_rules.ADMIN_ROLE


def _names(value):
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception:
			raise BadRequestError(_("{0} must be valid JSON.").format("set_types")) from None
	if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
		raise BadRequestError(_("{0} has the wrong type.").format("set_types"))
	return value


def _ref(value):
	try:
		return int(value)
	except (TypeError, ValueError):
		raise BadRequestError(_("{0} has the wrong type.").format("next_ref")) from None


@frappe.whitelist(methods=["GET"])
def status():
	"""Prefix đã khai, dải mã còn lại và quyền quản lý, cho form Settings và form loại bộ mới."""
	return {
		"ok": True,
		"prefix": gs1.declared_company_prefix(),
		"range": code_registry.gtin_range(),
		"can_manage": ADMIN_ROLE in frappe.get_roles(),
	}


@frappe.whitelist(methods=["GET"])
def backfill_preview():
	"""Danh sách sẽ cấp GTIN-14; chỉ đọc nên từ chối không ghi Audit Log."""
	require_any_role(ADMIN_ROLE)
	try:
		return {"ok": True, **gtin_rules.backfill_preview()}
	except BlockedError as error:
		return {"ok": False, "error": error.block.as_dict()}


@frappe.whitelist(methods=["POST"])
@idempotent
def backfill(set_types, next_ref, reason=None, client_ts=None):
	"""Cấp đúng danh sách đã xem. Từ chối: ``GTIN_BACKFILL_STALE``, ``GS1_PREFIX_NOT_DECLARED``,
	``GTIN_RANGE_EXHAUSTED`` (409), ``REASON_REQUIRED`` (422)."""
	require_any_role(ADMIN_ROLE)
	timestamp = parse_client_ts(client_ts)
	try:
		return {"ok": True, **gtin_rules.backfill(_names(set_types), _ref(next_ref), reason)}
	except BlockedError as error:
		return reject_block(error.block, gtin_rules.SET_TYPE, client_ts=timestamp)


@frappe.whitelist(methods=["POST"])
@idempotent
def change_locked(set_type, gtin, reason, client_ts=None):
	"""R10 đổi GTIN đã in lên nhãn. Từ chối: ``REASON_REQUIRED`` (422), ``GTIN_NOT_LOCKED`` (409)."""
	require_any_role(ADMIN_ROLE)
	timestamp = parse_client_ts(client_ts)
	try:
		return {"ok": True, "set_type": set_type, "gtin": gtin_rules.change_locked(set_type, gtin, reason)}
	except BlockedError as error:
		return reject_block(error.block, gtin_rules.SET_TYPE, set_type, client_ts=timestamp)
