"""Vô hiệu mã TB- của thiết bị đã Retired trước FEAT-005 (A-05 R4, FR-M9-07.2); chạy lại không lỗi, không đổi gì thêm.

Từ FEAT-005, `equipment.status.set_status(..., "Retired")` vô hiệu mã cùng transaction; máy ngừng sử dụng trước đó
còn mã ``Active`` trong Code Registry nên vẫn in được nhãn. Lý do vô hiệu = lý do ngừng sử dụng đã lưu, không có thì
một câu chung đã dịch.
"""

import frappe
from frappe import _

from tracecore.core import code_registry


def execute():
	rows = frappe.get_all(
		"Equipment", filters={"status": "Retired"}, fields=["name", "retired_reason"], order_by="name"
	)
	for row in rows:
		if frappe.db.get_value("Code Registry", row.name, "status") != "Active":
			continue  # chưa có trong sổ hoặc đã Disabled
		reason = (row.retired_reason or "").strip() or _("Equipment retired before its QR code was disabled")
		code_registry.disable(row.name, reason)
