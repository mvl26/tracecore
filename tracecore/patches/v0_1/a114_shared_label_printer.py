"""A-114: một máy in nhãn chung, nhãn in ra PDF qua hộp thoại In.

- Print Job ``Waiting`` (chờ máy in/cuộn đúng loại) chuyển ``Queued`` để in được qua PDF ngay.
- Site chỉ có đúng một máy in đang dùng và chưa chọn máy in nhãn chung → chọn máy đó.
- Khổ nhãn chung chưa đặt → 60 x 40 mm.
"""

import frappe

SETTINGS = "TraceCore Settings"


def execute():
	frappe.db.sql("update `tabPrint Job` set status = 'Queued' where status = 'Waiting'")
	if not frappe.db.get_single_value(SETTINGS, "label_printer"):
		active = frappe.get_all("Printer", filters={"is_active": 1}, pluck="name")
		if len(active) == 1:
			frappe.db.set_single_value(SETTINGS, "label_printer", active[0])
	for field, default in (("label_width_mm", 60), ("label_height_mm", 40)):
		if not frappe.db.get_single_value(SETTINGS, field):
			frappe.db.set_single_value(SETTINGS, field, default)
