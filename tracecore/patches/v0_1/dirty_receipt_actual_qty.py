"""A-94: dòng của phiếu tiếp nhận còn nháp điền sẵn số thực tế theo BOM. Phiếu đã ghi sổ giữ nguyên: lúc đó chưa đếm."""

import frappe


def execute():
	line = frappe.qb.DocType("Dirty Receipt Confirm Line")
	receipt = frappe.qb.DocType("Dirty Receipt")
	(
		frappe.qb.update(line)
		.join(receipt)
		.on(line.parent == receipt.name)
		.set(line.actual_qty, line.qty)
		.where(receipt.docstatus == 0)
		.run()
	)
