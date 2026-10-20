"""Tạo mẫu nhãn gói mẫu (Pack label - Steam/Plasma) cho site đã cài trước FEAT-018; không ghi đè mẫu đã có."""

from tracecore.setup.label_templates import ensure_sample_templates


def execute():
	ensure_sample_templates()
