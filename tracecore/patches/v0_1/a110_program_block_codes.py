"""A-110 D11: thêm hai mã từ chối chương trình theo loại bộ vào mã lỗi TB-005 của site đang chạy.

``ensure_error_codes`` chỉ thêm mã còn thiếu, không sửa mã đã có (viện có thể đã chỉnh), nên dòng TB-005 cũ không tự có
hai mã mới. Patch chỉ nối thêm mã còn thiếu, giữ nguyên các dòng khác.
"""

import frappe

from tracecore.core import error_codes

CATALOG = "TB-005"
BLOCK_CODES = ("PROGRAM_NOT_FOR_SET", "PROGRAM_OVERRIDE_REASON_REQUIRED")


def execute():
	if not frappe.db.exists("TraceCore Error Code", CATALOG):
		return
	lines = [
		line.strip()
		for line in (frappe.db.get_value("TraceCore Error Code", CATALOG, "block_codes") or "").splitlines()
		if line.strip()
	]
	added = [code for code in BLOCK_CODES if code not in lines]
	if added:
		frappe.db.set_value(
			"TraceCore Error Code", CATALOG, "block_codes", "\n".join(lines + added), update_modified=False
		)
		error_codes.clear_cache()
