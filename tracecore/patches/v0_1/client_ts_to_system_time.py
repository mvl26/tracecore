"""A-74: `client_ts` của Sync Conflict và TraceCore Error Log lưu giờ hệ thống; đổi các dòng đã lưu UTC."""

import frappe

from tracecore.core.client_time import to_system_time


def execute():
	for doctype in ("Sync Conflict", "TraceCore Error Log"):
		if not frappe.db.table_exists(doctype):
			continue
		for row in frappe.get_all(
			doctype, filters={"client_ts": ["is", "set"]}, fields=["name", "client_ts"]
		):
			frappe.db.set_value(
				doctype, row.name, "client_ts", to_system_time(row.client_ts), update_modified=False
			)
