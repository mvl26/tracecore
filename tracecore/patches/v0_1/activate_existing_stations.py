"""Đặt ``is_active = 1`` cho khu và trạm đã có khu trước FEAT-002 (cột mới `is_active` của dòng cũ là 0)."""

import frappe


def execute():
	# Trường mới nên chưa ai từng tắt; trạm chưa có khu vẫn không hoạt động (FR-M9-03.3)
	frappe.db.sql(
		"""update `tabZone Station` set is_active = 1
		where is_active = 0 and (is_zone = 1 or ifnull(parent_zone, '') != '')"""
	)
