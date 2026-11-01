"""Khóa phiên bản mã màn trạm cho boot: trình duyệt so để bỏ script Page trong localStorage (tc_page_cache.js)."""

import hashlib
import os

import frappe

_PAGE_FILES = ("ui/page/station/station.js", "ui/page/station/station.css", "ui/page/station/station.html")


def _read(path):
	with open(path, "rb") as handle:
		return handle.read()


def station_build():
	"""Băm nội dung các file tạo nên Page trạm, gồm cả script nối thêm qua hook ``page_js``."""
	joined = frappe.get_hooks("page_js", app_name="tracecore").get("station") or []
	digest = hashlib.sha256()
	for path in (*_PAGE_FILES, *joined):
		digest.update(_read(frappe.get_app_path("tracecore", *path.split("/"))))
	return digest.hexdigest()[:16]


def extend_bootinfo(bootinfo):
	"""Chạy ở mỗi lần tải Desk, sau phần boot đã cache, nên không phụ thuộc clear-cache."""
	bootinfo.tc_station_build = station_build()
