"""RPC thanh lý bộ trên Desk (FEAT-004, A-37 a): ``tracecore.v1.set_unit.disposal_*`` (công bố lại ở `set_unit`).

R02 đề nghị kèm lý do, R01 duyệt/từ chối bằng PIN; quyền và luật do `instrument.disposal` kiểm. Lỗi nghiệp vụ trả
body ``ok: false`` (Audit Log ``Reject``), không ném, như các RPC Desk khác.
"""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.instrument import disposal
from tracecore.v1._common import reject_block


def _run(set_unit, call):
	try:
		return {"ok": True, **call()}
	except BlockedError as error:
		return reject_block(error.block, disposal.DOCTYPE, set_unit)


@frappe.whitelist(methods=["POST"])
def disposal_request(set_unit, reason=None):
	"""R02 đề nghị thanh lý bộ Hết vòng đời hoặc rẽ nhánh Thanh lý ở T3."""
	return _run(set_unit, lambda: disposal.request(set_unit, reason))


@frappe.whitelist(methods=["POST"])
def disposal_approve(set_unit, note=None, pin=None):
	"""R01 duyệt bằng PIN: bộ Đã thanh lý, Set ID vô hiệu."""
	return _run(set_unit, lambda: disposal.approve(set_unit, note, pin))


@frappe.whitelist(methods=["POST"])
def disposal_reject(set_unit, note=None, pin=None):
	"""R01 từ chối bằng PIN kèm ghi chú."""
	return _run(set_unit, lambda: disposal.reject(set_unit, note, pin))
