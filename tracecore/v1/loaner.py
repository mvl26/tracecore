"""RPC tracecore.v1.loaner.* — bộ mượn trên Desk (FEAT-017, A-38; UC-04, SCR-04, API-M1-05).

Nhận = ghi sổ phiếu `Loaner Set` (quyền submit của R02); trả hãng và gia hạn qua `instrument.loaner`. Lỗi nghiệp vụ
trả body ``ok: false`` (Audit Log ``Reject``), không ném, như các RPC Desk khác.
"""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.instrument import loaner as service
from tracecore.v1._common import reject_block


def _run(name, call):
	try:
		return {"ok": True, **call()}
	except BlockedError as error:
		return reject_block(error.block, service.DOCTYPE, name)


def _receive(name):
	doc = frappe.get_doc(service.DOCTYPE, name)
	doc.submit()
	return {"name": doc.name, "status": "Received", "set_unit": doc.set_unit, "set_type": doc.set_type}


@frappe.whitelist(methods=["POST"])
def receive(name):
	"""Ghi sổ phiếu nháp = nhận bộ mượn: dụng cụ, loại bộ mượn, Set ID LN (FR-M1-07, FR-M1-05.5)."""
	return _run(name, lambda: _receive(name))


@frappe.whitelist(methods=["POST"])
def return_set(name, lines=None, note=None):
	"""Biên bản trả: `lines` = ``[{idx, returned_qty, damaged_qty, note}]`` (JSON) cho mọi dòng BOM (FR-M1-07.2)."""
	return _run(name, lambda: service.return_set(name, lines, note))


@frappe.whitelist(methods=["POST"])
def extend(name, expected_return=None, reason=None):
	"""Gia hạn ngày trả kèm lý do (UC-04 A2)."""
	return _run(name, lambda: service.extend(name, expected_return, reason))
