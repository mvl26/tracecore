"""Ngữ cảnh Print Format "TC Linen Receipt": biên nhận thu gom đồ vải (FEAT-033, FR-M3-01.5, UC-16 bước 5; A-49 L7).

Hàm được đăng ký ở `hooks.jinja` để format gọi `tc_linen_receipt_context(doc.name)` khi in từ Desk hoặc từ màn trạm.
Chỉ người đọc được phiếu mới in được. Số kg dùng dấu phẩy thập phân (NFR-L10N-01).
"""

import frappe
from frappe.utils import cint, flt, formatdate

from tracecore.instrument.count_sheet import token_values

DOCTYPE = "Linen Collection"
RECEIPT_FORMAT = "TC Linen Receipt"


def kg(value) -> str:
	"""12.5 thành "12,5"; bỏ số 0 thừa, tối đa 3 chữ số lẻ."""
	text = f"{flt(value):.3f}".rstrip("0").rstrip(".")
	return (text or "0").replace(".", ",")


def tc_linen_issue_context(name: str) -> dict:
	"""Ngữ cảnh Print Format "TC Linen Issue Receipt" (FEAT-035, FR-M3-05.1): biên nhận cấp phát kèm chữ ký người nhận."""
	doc = frappe.get_doc("Linen Issue", name)
	doc.check_permission("read")
	issued = doc.issued_at
	return {
		"tc": token_values(),
		"name": doc.name,
		"draft": doc.docstatus == 0,
		"cancelled": doc.docstatus == 2,
		"kind": doc.kind,
		"department": frappe.db.get_value("Department", doc.department, "department_name") or doc.department,
		"issued_at": (
			f"{formatdate(issued, 'dd/mm/yyyy')} {frappe.utils.get_datetime(issued).strftime('%H:%M')}"
			if issued
			else ""
		),
		"issued_by": frappe.db.get_value("Employee", doc.issued_by, "employee_name") or doc.issued_by or "",
		"recipient": doc.recipient_name or doc.recipient or "",
		"sign_method": doc.sign_method or "",
		"signature": doc.signature if doc.sign_method == "Touch" else "",
		"reason": doc.reason or "",
		"total_qty": cint(doc.total_qty),
		"total_weight": kg(doc.total_weight_kg),
		"quota_warning": doc.quota_warning or "",
		"note": doc.note or "",
		"items": [
			{
				"index": row.idx,
				"name": row.linen_type,
				"qty": cint(row.qty),
				"weight": kg(row.weight_kg),
				"variance_note": row.variance_note or "",
			}
			for row in doc.lines
		],
	}


def tc_linen_receipt_context(name: str) -> dict:
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	collected = doc.collected_at
	return {
		"tc": token_values(),
		"name": doc.name,
		"draft": doc.docstatus == 0,
		"cancelled": doc.docstatus == 2,
		"department": frappe.db.get_value("Department", doc.department, "department_name") or doc.department,
		"collected_at": (
			f"{formatdate(collected, 'dd/mm/yyyy')} {frappe.utils.get_datetime(collected).strftime('%H:%M')}"
			if collected
			else ""
		),
		"delivered_by": doc.delivered_by,
		"received_by": frappe.db.get_value("Employee", doc.received_by, "employee_name")
		or doc.received_by
		or "",
		"station": doc.station or "",
		"total_qty": cint(doc.total_qty),
		"total_weight": kg(doc.total_weight_kg),
		"note": doc.note or "",
		"items": [
			{
				"index": row.idx,
				"name": row.linen_type,
				"qty": cint(row.qty),
				"weight": kg(row.weight_kg),
				"contaminated": cint(row.contaminated),
				"variance_note": row.variance_note or "",
			}
			for row in doc.lines
		],
	}
