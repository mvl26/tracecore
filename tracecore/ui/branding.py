"""Tên bệnh viện cạnh logo trên thanh điều hướng Desk (tc_launcher.js).

Mỗi site là một bệnh viện: tên lấy từ Website Settings, ô App Name; logo từ ô App Logo (Frappe tự đọc).
Chưa đặt tên thì giữ "TraceCore".
"""

import frappe

DEFAULT_BRAND = "TraceCore"
# giá trị mặc định của Frappe, không phải tên bệnh viện
_FRAMEWORK_NAMES = {"Frappe", "ERPNext"}


def brand_name():
	name = (frappe.get_website_settings("app_name") or "").strip()
	return name if name and name not in _FRAMEWORK_NAMES else DEFAULT_BRAND


def extend_bootinfo(bootinfo):
	bootinfo.tc_brand = brand_name()
