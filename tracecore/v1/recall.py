"""RPC tracecore.v1.recall.* — lệnh thu hồi từ Desk (FEAT-029, UC-14, SCR-14, WF-05, API-M2-14/15).

Lập lệnh và đóng lệnh chỉ R01/R02; xác nhận từng gói theo vai trò của dòng (dịch vụ kiểm). Lỗi nghiệp vụ trả body
``ok: false`` (Audit Log ``Reject``), không ném, như các RPC Desk khác. Xác nhận trên PDA thuộc FEAT-009.
"""

import frappe
from frappe import _

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import recall as service
from tracecore.v1._common import reject_block

SUMMARY_FIELDS = (
	"name",
	"status",
	"trigger",
	"sterilization_load",
	"indicator_lot",
	"pack_count",
	"confirmed_count",
)


def _summary(doc):
	return {key: doc.get(key) for key in SUMMARY_FIELDS}


def _run(ref_name, call):
	try:
		return {"ok": True, "recall": _summary(call())}
	except BlockedError as error:
		return reject_block(error.block, service.DOCTYPE, ref_name)


@frappe.whitelist(methods=["POST"])
def create(load=None, lot=None, reason=None):
	"""Lập lệnh thu hồi theo mẻ `load` hoặc lô chỉ thị `lot` kèm lý do (FR-M2-20, UC-14 A1)."""
	if not (load or lot):
		frappe.throw(_("Choose a sterilization load or an indicator lot to recall."))
	return _run(load or lot, lambda: service.create(load=load or None, lot=lot or None, reason=reason))


@frappe.whitelist(methods=["POST"])
def confirm_pack(recall, pack, note=None):
	"""Xác nhận một gói của lệnh (khóa trong kho / khoa đã trả / đã báo bác sĩ)."""
	return _run(recall, lambda: service.confirm_pack(recall, pack, note))


@frappe.whitelist(methods=["POST"])
def close(recall):
	"""Đóng lệnh khi mọi gói đã xác nhận (FR-M2-20.2)."""
	return _run(recall, lambda: service.close(recall))
