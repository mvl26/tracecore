"""Ô truy cập nhanh trên navbar Desk (NAV-05, tc_launcher.js + tc_quick_nav.js).

Server tính sẵn ô tài khoản mở được và gửi trong boot, để navbar không hiện ô dẫn tới màn không có quyền.
"""

import frappe

from tracecore.v1 import navigation


def extend_bootinfo(bootinfo):
	try:
		bootinfo.tc_quick_nav = navigation.quick_nav_keys()
	except Exception:
		# lỗi ở boot làm hỏng cả Desk: thiếu thanh truy cập nhanh thì vẫn dùng được sidebar trang chủ
		frappe.log_error("TraceCore quick navigation")
		bootinfo.tc_quick_nav = []
