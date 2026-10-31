"""Kiểm mã của Link có `fetch_from` trên DocType TraceCore (A-65).

`BaseDocument.get_invalid_links` của Frappe v15: Link có trường fetch mà mã không tồn tại thì `get_value` trả None và
bị bỏ qua, nên không báo lỗi. Cột Tên A-65 làm mọi Link `in_list_view` rơi vào nhánh đó, vì vậy kiểm lại tại đây.
Link không có trường fetch vẫn do Frappe kiểm. Tôn trọng ``flags.ignore_links`` như Frappe.
"""

import frappe
from frappe import _

from tracecore.core.name_columns import MODULES


def _missing_links(doc):
	for df in doc.meta.get_link_fields():
		value = doc.get(df.fieldname)
		if not value or not df.options or not doc.meta.get_fields_to_fetch(df.fieldname):
			continue
		target = frappe.get_meta(df.options)
		if target.issingle or target.get("is_virtual"):
			continue
		if not frappe.db.exists(df.options, value):
			yield f"{_(df.label, context=df.parent)}: {value}"


def validate_fetched_links(doc, method=None):
	"""doc_events `*` validate: chặn mã không tồn tại ở Link có fetch, gồm cả dòng bảng con."""
	if doc.flags.ignore_links or doc.meta.module not in MODULES:
		return
	missing = [text for row in (doc, *doc.get_all_children()) for text in _missing_links(row)]
	if missing:
		frappe.throw(_("Could not find {0}").format(", ".join(missing)), frappe.LinkValidationError)
