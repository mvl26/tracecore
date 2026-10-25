"""FEAT-016 (A-09 G6): Set Unit có trước FEAT-016 nhận ``cycles_source = System``; chạy lại không đổi gì thêm.

Số chu trình của bộ cũ do hệ thống đếm (``System``); không bịa khoa hay dữ liệu khác (Global Constraints). Ghi thẳng DB
(không qua validate: ``cycles_source`` chỉ ghi khi cấp), không đổi ``modified``. ``tag_verified_on/by`` để trống.
"""

import frappe


def execute():
	names = frappe.db.sql_list(
		"select name from `tabSet Unit` where ifnull(cycles_source, '') = '' order by name"
	)
	for name in names:
		frappe.db.set_value("Set Unit", name, "cycles_source", "System", update_modified=False)
