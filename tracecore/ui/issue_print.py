"""Dữ liệu cho Print Format ``TC Issue Note`` (phiếu cấp phát T7, FEAT-026 C10, FR-M2-15.1).

Nằm ở module ``ui`` (lớp trình bày) vì phiếu in cần token giao diện của ``instrument.count_sheet`` mà module M2
(``reprocessing``) không được import chéo (ADR-001). Hàm đăng ký trong ``hooks.jinja`` như ``tc_count_sheet_context``.
"""

import base64
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, formatdate, get_datetime

from tracecore.core import qr
from tracecore.instrument.count_sheet import DATETIME_FORMAT, token_values

CONTEXT = "TC Issue Note"
TRACE_REPORT = "Pack Trace"
TITLE_FIELDS = ("name", "set_type_name")


def _stamp(value):
	return get_datetime(value).strftime(DATETIME_FORMAT) if value else ""


def trace_url(name: str) -> str:
	"""Đường dẫn tuyệt đối tới báo cáo Pack Trace lọc theo phiếu cấp phát `name` (payload QR của phiếu, A-124)."""
	return frappe.utils.get_url(f"/app/query-report/{quote(TRACE_REPORT)}?issue_note={quote(name)}")


def trace_qr(name: str) -> str:
	"""Ảnh QR (data URI PNG, sinh tại server bằng ``core.qr``) của ``trace_url(name)``."""
	png = qr.qr_png(trace_url(name), module_px=4, margin_px=16)
	return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def tc_issue_note_context(name: str) -> dict:
	"""Ngữ cảnh in của một phiếu cấp phát: người cấp, người nhận, chữ ký, gói, duyệt R02 và token giao diện.

	Chỉ người có quyền đọc phiếu mới in được (``frappe.has_permission``); phiếu nháp in được nhưng ghi rõ chưa ký.
	"""
	doc = frappe.get_doc("Issue Note", name)
	doc.check_permission("read")
	issuer = frappe.db.get_value("User", doc.issued_by_user, "full_name") or doc.issued_by_user
	approver = (
		frappe.db.get_value("User", doc.approved_by, "full_name") or doc.approved_by
		if doc.approved_by
		else None
	)
	return {
		"tc": token_values(),
		"name": doc.name,
		"draft": doc.docstatus == 0,
		"department": doc.department,
		"department_name": frappe.db.get_value("Department", doc.department, "department_name")
		or doc.department,
		"issued_at": _stamp(doc.issued_at),
		"issued_by": issuer,
		"recipient": doc.recipient_name or doc.recipient,
		"recipient_department": doc.recipient_department,
		"dept_mismatch_reason": doc.dept_mismatch_reason,
		"sign_method": doc.sign_method,
		"sign_method_label": _("Employee card", context=CONTEXT)
		if doc.sign_method == "Card"
		else _("Signature on screen", context=CONTEXT),
		"signature": doc.signature if doc.sign_method == "Touch" else None,
		"signed_at": _stamp(doc.signed_at),
		"approved_by": approver,
		"approved_at": _stamp(doc.approved_at),
		"packs": [
			{
				"index": index,
				"cycle_id": row.pack,
				"set_id": row.set_unit,
				"set_name": row.set_name,
				"expiry": formatdate(row.expiry, "dd/mm/yyyy") if row.expiry else "",
				"fefo_note": row.fefo_note,
			}
			for index, row in enumerate(doc.packs, start=1)
		],
		"pack_count": cint(doc.pack_count),
		# A-124: một QR cho cả phiếu, mở Pack Trace lọc theo số phiếu (chuỗi T1→T7 của mọi bộ trong phiếu)
		"trace_url": trace_url(doc.name),
		"trace_qr": trace_qr(doc.name),
		"printed_at": _stamp(frappe.utils.now_datetime()),
		"printed_by": frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user,
	}
