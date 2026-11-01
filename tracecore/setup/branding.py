"""Thương hiệu trang đăng nhập (#1830 G-01). Bước tay, không gắn vào migrate.

    bench --site <site> execute tracecore.setup.branding.apply_login_branding

`Website Settings.app_name` áp cho toàn site: trên site dùng chung nhiều app, mọi app đều thấy tên này ở trang đăng nhập.
Vì vậy chỉ chạy khi site dành riêng cho TraceCore hoặc đã đồng ý. Tên đã có người đặt thì giữ nguyên.
Repo chưa có logo được duyệt nên chỉ đổi chữ; tiêu đề tiếng Việt lấy từ `translations/vi.csv`.
"""

import frappe

APP_NAME = "TraceCore"
DEFAULT_NAMES = ("", "Frappe")


def apply_login_branding():
	current = frappe.db.get_single_value("Website Settings", "app_name") or ""
	if current not in DEFAULT_NAMES:
		return {"changed": False, "app_name": current}
	frappe.db.set_single_value("Website Settings", "app_name", APP_NAME)
	frappe.clear_cache()
	return {"changed": True, "app_name": APP_NAME}
