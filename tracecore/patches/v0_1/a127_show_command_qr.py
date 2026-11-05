"""A-127: bật sẵn QR mã lệnh cạnh nút xác nhận cho site đang chạy (mặc định của Single chỉ áp khi cài mới).

Chỉ đặt khi chưa có giá trị; R10 đã tắt thì giữ nguyên.
"""

import frappe

SETTINGS = "TraceCore Settings"
FIELD = "show_command_qr"


def execute():
	stored = frappe.db.sql("select value from tabSingles where doctype=%s and field=%s", (SETTINGS, FIELD))
	if not stored:
		frappe.db.set_single_value(SETTINGS, FIELD, 1)
