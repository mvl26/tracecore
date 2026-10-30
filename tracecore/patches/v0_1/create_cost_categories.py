"""Tạo 12 khoản mục chi phí hệ thống cho site đã cài trước FEAT-044; không ghi đè khoản mục đã có."""

from tracecore.costing.setup import ensure_categories


def execute():
	ensure_categories()
