"""Trang công khai của mã QR tài liệu truyền thông: ``/tai-lieu/<doc_code>`` (FEAT-073; FR-M17-06, FR-M17-06.1; UC-56
bước 6, E4; A-151 Q3).

Người bệnh, người nhà quét QR dán tại khoa, không cần đăng nhập. Trang luôn mở bản hiện hành của mã tài liệu (bản mới
cùng mã thay bản cũ nên QR đã in vẫn đúng); bản Nháp chưa ban hành, bản đã thu hồi hoặc mã không phải Tài liệu truyền
thông → thông báo, không có file. File vẫn riêng tư, chỉ ``tracecore.v1.food_safety.material_file`` trả nội dung.
"""

from urllib.parse import quote

import frappe
from frappe import _

from tracecore.infection_program import procedure_documents as documents

no_cache = 1
FILE_METHOD = "/api/method/tracecore.v1.food_safety.material_file"


def get_context(context):
	code = (frappe.form_dict.get("code") or "").strip()
	current = documents.current_material(code) if code else {"state": "missing"}
	context.no_cache = 1
	context.state = current["state"]
	context.title = current.get("title") or _("Communication material")
	context.version_no = current.get("version_no")
	context.issued_on = current.get("issued_on")
	context.file_link = (
		f"{FILE_METHOD}?code={quote(code, safe='')}"
		if current["state"] == "current" and current.get("file")
		else ""
	)
	context.notice = {
		"current": "" if context.file_link else _("The file of this document has not been attached yet."),
		"draft": _("This document has not been issued yet."),
		"withdrawn": _("This document has been withdrawn."),
		"missing": _("Document not found."),
	}[current["state"]]
	return context
