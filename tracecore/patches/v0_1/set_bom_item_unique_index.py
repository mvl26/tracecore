"""Tạo chỉ mục unique (``set_type``, ``bom_version``, ``instrument``) của Set BOM Item trên site có dữ liệu cũ (S4).

``set_bom_item.on_doctype_update`` chỉ chạy khi JSON DocType đổi, nên site còn dòng trùng ở lần migrate FEAT-015 sẽ
không có chỉ mục nếu chỉ dựa vào nó. Hết nhóm trùng → tạo chỉ mục (``add_unique`` bỏ qua khi đã có: chạy lại không đổi
gì). Còn trùng → in từng nhóm và không tạo (phiên bản bất biến: patch không tự sửa dòng). Frappe chỉ chạy một patch một
lần, nên sau khi gộp dòng trùng bằng tay, chạy lại
``bench --site <site> execute tracecore.patches.v0_1.set_bom_item_unique_index.execute``.
"""

import frappe

from tracecore.instrument.doctype.set_bom_item.set_bom_item import (
	UNIQUE_CONSTRAINT,
	UNIQUE_FIELDS,
	duplicate_lines,
)

ITEM = "Set BOM Item"


def execute():
	duplicates = duplicate_lines()
	if duplicates:
		for row in duplicates:
			print(
				f"Set type {row.set_type} BOM version {row.bom_version}: instrument {row.instrument} is listed "
				f"{row.line_count} times; unique index {UNIQUE_CONSTRAINT} not created. Merge the lines, then run "
				"bench --site <site> execute tracecore.patches.v0_1.set_bom_item_unique_index.execute"
			)
		return
	frappe.db.add_unique(ITEM, list(UNIQUE_FIELDS), constraint_name=UNIQUE_CONSTRAINT)
