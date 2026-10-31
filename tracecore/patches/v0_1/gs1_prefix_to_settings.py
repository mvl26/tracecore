"""Mã doanh nghiệp GS1 khai trong TraceCore Settings (A-76): chép giá trị thật từ site_config nếu có."""

from tracecore.setup.gs1_settings import copy_site_config_prefix


def execute():
	copy_site_config_prefix()
