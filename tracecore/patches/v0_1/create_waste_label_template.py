"""Tạo mẫu nhãn QR `Object label - Waste Container` cho site đã cài trước FEAT-047; không ghi đè mẫu đã có."""

from tracecore.setup.label_templates import ensure_object_templates


def execute():
	ensure_object_templates()
