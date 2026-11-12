"""Ngưỡng KSDP 0 phút (ô trống bị Frappe lưu thành 0) đã đánh mọi ca "Quá sớm": tính lại kỳ chưa khóa thành Không đánh giá."""

import frappe


def execute():
	if not frappe.db.table_exists("Surgical Surveillance"):
		return
	from tracecore.hai_surveillance import ssi

	if ssi.threshold() is None:
		ssi.recalculate_prophylaxis()
