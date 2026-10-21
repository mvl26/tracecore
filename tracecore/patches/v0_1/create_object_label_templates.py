"""Tạo mẫu nhãn QR đối tượng (Object label - …) cho site đã cài trước FEAT-005; không ghi đè mẫu đã có."""

from tracecore.setup.label_templates import ensure_object_templates


def execute():
	ensure_object_templates()
