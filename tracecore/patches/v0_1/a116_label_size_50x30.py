"""A-116: khổ nhãn chung mặc định 50 x 30 mm.

Chỉ đổi khi khổ đang trống hoặc đúng mặc định cũ 60 x 40 mm; khổ người dùng đã đặt (khác 60 x 40) giữ nguyên.
"""

import frappe
from frappe.utils import flt

SETTINGS = "TraceCore Settings"
OLD_DEFAULT = (60, 40)
NEW_DEFAULT = (50, 30)


def execute():
	width = flt(frappe.db.get_single_value(SETTINGS, "label_width_mm"))
	height = flt(frappe.db.get_single_value(SETTINGS, "label_height_mm"))
	if (width, height) in (OLD_DEFAULT, (0, 0)):
		frappe.db.set_single_value(
			SETTINGS, {"label_width_mm": NEW_DEFAULT[0], "label_height_mm": NEW_DEFAULT[1]}
		)
