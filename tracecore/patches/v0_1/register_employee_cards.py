"""Ghi thẻ riêng của nhân viên đã có vào sổ mã để in được nhãn QR thẻ (FEAT-079, FR-M9-07.4).

Nhân viên lưu từ trước FEAT-079 có `tc_card_id` khác mã NV- nhưng chưa có trong `Code Registry`. Mã không hợp lệ làm
thẻ hoặc đã thuộc sổ thì bỏ qua; chạy lại không đổi.
"""

import frappe

from tracecore.hr import employees


def execute():
	for name in frappe.get_all("Employee", filters={"tc_card_id": ["is", "set"]}, pluck="name"):
		employees.register_card_code(frappe.get_doc("Employee", name))
