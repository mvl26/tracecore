"""RPC tracecore.v1.archive.* — xuất gói hồ sơ tiệt khuẩn lưu trữ và kiểm checksum (FEAT-012, FR-M9-12, A-58).

Đường Desk (không phải trạm/PDA nên không `@idempotent`). `export` tạo phiếu `Archive Export` theo quyền DocType
(TC R01, R10), phiếu tự xếp job nền; `verify` cần quyền đọc phiếu.
"""

import frappe
from frappe import _

from tracecore.admin_reports import archive

INCLUDE_FIELDS = {
	"loads": "inc_loads",
	"indicators": "inc_indicators",
	"machine_data": "inc_machine_data",
	"issues": "inc_issues",
	"usage": "inc_usage",
	"audit": "inc_audit",
}


@frappe.whitelist(methods=["POST"])
def export(
	scope_type="Period",
	from_date=None,
	to_date=None,
	sterilization_load=None,
	recall_order=None,
	include=None,
	full_patient_code=0,
	patient_code_reason=None,
):
	"""Tạo phiếu xuất; ``include``: danh sách JSON trong ``loads, indicators, machine_data, issues, usage, audit``
	(bỏ trống = tất cả). Trả ``{"ok", "name"}``."""
	chosen = frappe.parse_json(include) if isinstance(include, str) else include
	if chosen is not None and (not isinstance(chosen, list) or set(chosen) - set(INCLUDE_FIELDS)):
		frappe.throw(_("include must be a list of: {0}").format(", ".join(INCLUDE_FIELDS)))
	values = {
		"doctype": "Archive Export",
		"scope_type": scope_type,
		"from_date": from_date,
		"to_date": to_date,
		"sterilization_load": sterilization_load,
		"recall_order": recall_order,
		"full_patient_code": 1 if str(full_patient_code) in ("1", "true", "True") else 0,
		"patient_code_reason": patient_code_reason,
	}
	for key, field in INCLUDE_FIELDS.items():
		values[field] = 1 if chosen is None or key in chosen else 0
	doc = frappe.get_doc(values).insert()
	return {"ok": True, "name": doc.name}


@frappe.whitelist(methods=["GET", "POST"])
def verify(name):
	frappe.has_permission("Archive Export", "read", name, throw=True)
	return archive.verify(name)
