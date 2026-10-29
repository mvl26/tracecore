"""Ngữ cảnh Print Format "TC Stock Count Sheet": phiếu kiểm kê kho (FEAT-043, FR-M6-05, UC-26; A-52 C13).

Hàm được đăng ký ở `hooks.jinja` để format gọi `tc_stock_count_context(doc.name)`. Chỉ người đọc được phiếu mới in được. Số
lượng dùng dấu phẩy thập phân, ngày dd/mm/yyyy (NFR-L10N-01).
"""

import frappe
from frappe.utils import flt, formatdate

from tracecore.instrument.count_sheet import token_values

DOCTYPE = "Stock Reconciliation"
SHEET_FORMAT = "TC Stock Count Sheet"


def qty(value) -> str:
	"""12.5 thành "12,5"; bỏ số 0 thừa, tối đa 3 chữ số lẻ."""
	text = f"{flt(value):.3f}".rstrip("0").rstrip(".")
	return (text or "0").replace(".", ",")


def tc_stock_count_context(name: str) -> dict:
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	expiry = {
		row.name: row.expiry_date
		for row in frappe.get_all(
			"Batch",
			filters={"name": ["in", [r.batch_no for r in doc.items if r.batch_no] or [""]]},
			fields=["name", "expiry_date"],
		)
	}
	return {
		"tc": token_values(),
		"name": doc.name,
		"draft": doc.docstatus == 0,
		"cancelled": doc.docstatus == 2,
		"company": doc.company,
		"posting_date": formatdate(doc.posting_date, "dd/mm/yyyy") if doc.posting_date else "",
		"warehouses": sorted({row.warehouse for row in doc.items if row.warehouse}),
		"items": [
			{
				"index": row.idx,
				"item": row.item_code,
				"item_name": row.item_name or "",
				"batch": row.batch_no or "",
				"expiry": formatdate(expiry[row.batch_no], "dd/mm/yyyy") if expiry.get(row.batch_no) else "",
				"system": qty(row.current_qty),
				"counted": qty(row.qty),
				"difference": qty(row.quantity_difference),
				"reason": row.get("tc_variance_reason") or "",
			}
			for row in doc.items
		],
	}
