"""RPC tracecore.v1.incident.* — sự cố / NC / CAPA từ Desk (FEAT-030, UC-15, SCR-15, WF-06, API-M2-16).

Quyền tạo theo ma trận DT-INCIDENT (Custom DocPerm); chuyển bước, đóng, hủy do dịch vụ kiểm (chỉ R01/R02). Lỗi nghiệp
vụ trả body ``ok: false`` (Audit Log ``Reject``), không ném, như các RPC Desk khác.
"""

import frappe
from frappe import _

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import incidents as service
from tracecore.v1._common import reject_block

CREATE_FIELDS = (
	"incident_type",
	"severity",
	"description",
	"photo",
	*service.LINK_FIELDS,
	"department",
	"station",
)
STEPS = {"start_analysis": service.start_analysis, "submit_verification": service.submit_verification}
SUMMARY_FIELDS = ("name", "status", "incident_type", "severity", "docstatus")


def _summary(doc):
	return {key: doc.get(key) for key in SUMMARY_FIELDS}


def _run(ref_name, call):
	try:
		return {"ok": True, "incident": _summary(call())}
	except BlockedError as error:
		return reject_block(error.block, service.DOCTYPE, ref_name)


@frappe.whitelist(methods=["POST"])
def create(**values):
	"""Ghi nhận sự cố (FR-M2-21): loại, mức, mô tả, ảnh và ít nhất một đối tượng liên kết."""
	frappe.has_permission(service.DOCTYPE, "create", throw=True)
	clean = {key: values.get(key) for key in CREATE_FIELDS if values.get(key)}
	return _run(None, lambda: service.create(clean))


@frappe.whitelist(methods=["POST"])
def advance(incident, step):
	"""Bước không cần dữ liệu thêm: ``start_analysis`` (New → Analysis), ``submit_verification`` (CAPA → Verification)."""
	if step not in STEPS:
		frappe.throw(_("Unknown incident step: {0}").format(step))
	return _run(incident, lambda: STEPS[step](incident))


@frappe.whitelist(methods=["POST"])
def plan_capa(incident, root_cause=None, actions=None):
	"""Analysis → CAPA với nguyên nhân gốc và danh sách hành động (JSON); bỏ trống thì dùng dữ liệu đã lưu trên form."""
	rows = frappe.parse_json(actions) if isinstance(actions, str) else actions
	return _run(incident, lambda: service.plan_capa(incident, root_cause, rows))


@frappe.whitelist(methods=["POST"])
def complete_action(incident, action, result):
	"""Người phụ trách (hoặc R01/R02) ghi kết quả một hành động CAPA."""
	return _run(incident, lambda: service.complete_action(incident, action, result))


@frappe.whitelist(methods=["POST"])
def close(incident, verification_result):
	"""Verification → Closed (R01/R02), cần kết quả kiểm tra hiệu quả."""
	return _run(incident, lambda: service.close(incident, verification_result))


@frappe.whitelist(methods=["POST"])
def cancel(incident, reason):
	"""Hủy sự cố còn mở (R01/R02), bắt buộc lý do."""
	return _run(incident, lambda: service.cancel(incident, reason))
