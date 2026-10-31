"""Chuyển mã doanh nghiệp GS1 từ site_config sang TraceCore Settings (A-76)."""

import frappe

from tracecore.core import gs1

SETTINGS = "TraceCore Settings"


def copy_site_config_prefix():
	"""Chép ``tc_gs1_company_prefix`` thật sang Settings nếu viện chưa khai; mã demo hoặc sai định dạng thì bỏ qua."""
	if gs1.declared_company_prefix():
		return
	prefix = str(frappe.conf.get("tc_gs1_company_prefix") or "")
	if gs1.is_valid_gtin_prefix(prefix) and not gs1.is_demo_prefix(prefix):
		frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", prefix)
