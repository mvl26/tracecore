"""Điền mã thẻ cho nhân viên cũ chưa có (FEAT-078, mở rộng FEAT-036): `tc_card_id` = ID nhân viên (NV-#####).

Nhân viên mới đã được `hr.employees.after_insert` điền như vậy; patch này làm tương tự cho nhân viên có từ trước. Không đè
thẻ đã có; bỏ qua nhân viên mà mã của họ đã là thẻ của người khác (`tc_card_id` là duy nhất).
"""

import frappe

from tracecore.core.station_auth import normalize_card_id


def execute():
	empty = frappe.get_all(
		"Employee",
		or_filters=[["tc_card_id", "is", "not set"], ["tc_card_id", "=", ""]],
		pluck="name",
	)
	for name in empty:
		card = normalize_card_id(name)
		if frappe.db.exists("Employee", {"tc_card_id": card}):
			continue
		frappe.db.set_value("Employee", name, "tc_card_id", card, update_modified=False)
