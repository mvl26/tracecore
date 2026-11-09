"""RPC tracecore.v1.patient_code.* — xem mã người bệnh đầy đủ của DocType KSNK (FEAT-067; ADR-010 mở rộng; A-136 Q7).

Chỉ R01/R11 có quyền đọc chứng từ; lý do bắt buộc; Audit Log ``View Patient Code`` không chứa mã. Thiếu lý do trả
``{ok: false, error: REASON_REQUIRED}``.
"""

import frappe

from tracecore.core import patient_code
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import reject_block, require_any_role


@frappe.whitelist(methods=["POST"])
@idempotent
def reveal(doctype=None, name=None, reason=None, client_ts=None):
	"""``{"ok": true, "patient_code"}`` cho R01/R11."""
	require_any_role(*patient_code.REVEAL_ROLES)
	timestamp = parse_client_ts(client_ts)
	try:
		code = patient_code.reveal(doctype, name, reason)
	except BlockedError as error:
		return reject_block(error.block, doctype, name, client_ts=timestamp)
	return {"ok": True, "patient_code": code}
