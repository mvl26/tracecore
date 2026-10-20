"""Ghi Code Registry (prefix TR) cho trạm đã có trước FEAT-002 (fixtures TR-001..007); chạy lại không lỗi."""

import frappe

from tracecore.core import code_registry

STATION_PREFIX = "TR"


def execute():
	for name in frappe.get_all("Zone Station", filters={"is_zone": 0}, pluck="name", order_by="name"):
		if not code_registry.is_issued(name):
			code_registry.register(name, STATION_PREFIX, "Zone Station", name)
