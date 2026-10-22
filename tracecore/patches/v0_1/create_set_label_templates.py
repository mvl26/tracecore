"""Tạo mẫu thẻ kim loại (Set tag) và nhãn khay (Set tray label) cho site đã cài trước FEAT-016; không ghi đè mẫu đã có."""

from tracecore.setup.label_templates import ensure_set_templates


def execute():
	ensure_set_templates()
