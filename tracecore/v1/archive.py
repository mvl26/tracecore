"""RPC tracecore.v1.archive.* — xuất gói hồ sơ tiệt khuẩn lưu trữ và kiểm checksum (FEAT-012, FR-M9-12, A-58).

Đường Desk (không phải trạm/PDA nên không `@idempotent`). `export` tạo phiếu `Archive Export` theo quyền DocType
(TC R01, R10), phiếu tự xếp job nền; `verify` cần quyền đọc phiếu.
"""

import frappe
from frappe import _

from tracecore.admin_reports import archive, ic_dossier
from tracecore.core import dossier

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


# --- FEAT-074: gói hồ sơ KSNK cho đoàn kiểm tra (FR-M9-30; A-152; SCR-66) -----------------------------------------


def _require_dossier_role():
	if not ic_dossier.can_export():
		raise frappe.PermissionError(
			_("Only the head of infection control (R01) can export the infection control dossier.")
		)


@frappe.whitelist(methods=["GET"])
def ic_dossier_sections():
	"""Các phần của gói (khóa, nhãn đã dịch, có in PDF không) theo thứ tự."""
	_require_dossier_role()
	return {
		"ok": True,
		"sections": [
			{"key": section.key, "label": _(section.label), "in_pdf": bool(section.in_pdf)}
			for section in dossier.sections()
		],
	}


@frappe.whitelist(methods=["POST"])
def ic_dossier_export(from_month, to_month, sections=None):
	"""Tạo phiếu `Archive Export` phạm vi IC Dossier cho dải tháng ``YYYY-MM``; ``sections`` danh sách JSON (trống = tất
	cả). Job nền sinh ZIP; trả ``{"ok", "name"}``."""
	_require_dossier_role()
	months = dossier.months(from_month, to_month)
	ctx = dossier.context(months[0], months[-1])
	keys = ic_dossier.selected_keys(sections)
	doc = frappe.get_doc(
		{
			"doctype": "Archive Export",
			"scope_type": ic_dossier.SCOPE,
			"from_date": ctx.from_date,
			"to_date": ctx.to_date,
			"ic_sections": frappe.as_json(keys) if keys else None,
		}
	).insert()
	return {"ok": True, "name": doc.name}


@frappe.whitelist(methods=["GET"])
def ic_dossiers(limit=10):
	"""Các gói KSNK gần nhất (mới trước): trạng thái, dải tháng, Tạm, SHA-256, file."""
	_require_dossier_role()
	rows = frappe.get_all(
		"Archive Export",
		filters={"scope_type": ic_dossier.SCOPE},
		fields=[
			"name",
			"ic_months",
			"status",
			"provisional",
			"sha256",
			"archive_file",
			"generated_at",
			"error",
			"creation",
		],
		order_by="creation desc",
		limit=min(int(limit or 10), 50),
	)
	return {
		"ok": True,
		"dossiers": [
			{
				"name": row.name,
				"months": row.ic_months,
				"status": row.status,
				"provisional": bool(row.provisional),
				"sha256": row.sha256,
				"file": row.archive_file,
				"generated_at": str(row.generated_at) if row.generated_at else None,
				"error": row.error,
			}
			for row in rows
		],
	}
