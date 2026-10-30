"""RPC tracecore.v1.admin.* — chuyển trạng thái thủ công khi hệ thống lỗi (FEAT-004, A-37 b, FR-M2-00.3).

Chỉ R02, kèm lý do và số ticket sự cố; dịch vụ `reprocessing.manual_transition` kiểm và ghi Audit "Override" + NC.
Lỗi nghiệp vụ trả body ``ok: false`` (Audit Log ``Reject``), không ném.
"""

import frappe
from frappe import _

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import manual_transition
from tracecore.v1._common import reject_block

DOCTYPES = ("Set Unit", "Pack")


@frappe.whitelist(methods=["POST"])
def force_transition(doctype, name, status, reason=None, ticket=None, void_reason=None):
	"""Đổi trạng thái Set Unit hoặc Pack `name` sang `status`; Pack tới Void cần `void_reason`."""
	if doctype not in DOCTYPES:
		frappe.throw(_("Only a Set Unit or a Pack can be moved by hand."))
	try:
		if doctype == "Set Unit":
			result = manual_transition.force_set_status(name, status, reason, ticket)
		else:
			result = manual_transition.force_pack_status(
				name, status, reason, ticket, void_reason=void_reason
			)
	except BlockedError as error:
		return reject_block(error.block, doctype, name)
	return {"ok": True, **result}
