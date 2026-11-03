"""A-112 D2: thêm mã từ chối lô vật tư trên dòng (`CONSUMABLE_LOT_INVALID`) vào mã lỗi HC-004 của site đang chạy.

Như `a110_program_block_codes`: ``ensure_error_codes`` không sửa mã đã có, nên chỉ nối thêm mã còn thiếu.
"""

import frappe

from tracecore.core import error_codes

CATALOG = "HC-004"
BLOCK_CODES = ("CONSUMABLE_LOT_INVALID",)


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
