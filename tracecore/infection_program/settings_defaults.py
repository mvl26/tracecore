"""Giờ nhắc mặc định của IC Program Settings (mẫu số ngày, gói dự phòng — FR-M13-03, ADR-014).

Frappe v15 gán ``nowtime()`` cho mọi trường Time của bản ghi mới (``frappe.model.create_new.set_dynamic_default_values``),
bỏ qua ``default`` khai báo. Lần đầu IC Program Settings được tạo, giờ nhắc thành giờ lúc lưu thay vì 10:00.

Giá trị tự điền có phần lẻ giây (``14:33:33.168823``); giờ người dùng chọn trên form không bao giờ có. Chỉ những ô trống
hoặc có phần lẻ giây mới được đặt về mặc định khai báo trong DocType; giờ bệnh viện đã chọn giữ nguyên.
"""

import frappe

SETTINGS = "IC Program Settings"
REMINDER_FIELDS = ("census_reminder_time", "bundle_reminder_time")


def _auto_filled(value) -> bool:
	return not value or "." in str(value)


def ensure_reminder_times():
	meta = frappe.get_meta(SETTINGS)
	updates = {}
	for field in REMINDER_FIELDS:
		value = frappe.db.get_single_value(SETTINGS, field)
		if _auto_filled(value):
			updates[field] = meta.get_field(field).default
	if updates:
		frappe.db.set_single_value(SETTINGS, updates)
