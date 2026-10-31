"""Phiếu tiếp nhận người giao không có thẻ (`needs_card = 1`) chỉ có `deliverer_name`; `deliverer` từng bị Desk tự điền
bằng nhân viên của người tạo phiếu (User Permission). Xóa giá trị sai đó (FR-M2-01.7, A-30)."""

import frappe


def execute():
	frappe.db.sql(
		"update `tabDirty Receipt` set deliverer = null where needs_card = 1 and deliverer is not null"
	)
