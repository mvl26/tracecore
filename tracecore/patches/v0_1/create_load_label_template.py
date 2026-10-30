"""Tạo mẫu nhãn QR `Object label - Sterilization Load` cho site đã cài trước FEAT-022; không ghi đè mẫu đã có."""

from tracecore.setup.label_templates import ensure_object_templates


def execute():
	ensure_object_templates()
