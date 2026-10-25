"""FEAT-016 (A-13 G6): đổi giá trị ``Set Unit.cycles_source`` ``Actual`` → ``System``, ``Estimated`` → ``Estimate``.

Chạy lại không đổi gì thêm. Ghi thẳng DB, không đổi ``modified`` và không tạo Audit Log.
"""

import frappe

RENAMED = {"Actual": "System", "Estimated": "Estimate"}


def execute():
	for old, new in RENAMED.items():
		frappe.db.sql("update `tabSet Unit` set cycles_source = %s where cycles_source = %s", (new, old))
