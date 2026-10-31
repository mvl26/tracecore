"""Định mức hóa chất rửa theo ml và tiêu hao lại các lô đã báo lỗi (ticket T2 31/10/2026; A-72).

Hóa chất máy rửa nhập kho theo Can (1 Can = 5.000 ml) nhưng định mức một chu trình là phần lẻ của Can, mà ĐVT Can bắt buộc
số nguyên nên Stock Entry bị chặn và `CONSUMPTION_FAILED`. Patch này:

1. đổi định mức của các hóa chất tồn theo Can sang ml, thêm quy đổi ml cho Item và tắt "Phải là số nguyên" của ĐVT Can
   (`inventory.units.convert_chemical_norms`);
2. tiêu hao lại các lô rửa đã Đạt, đã có thông báo `CONSUMPTION_FAILED` mà chưa có phiếu xuất (`consume.retry`).

Chạy lại an toàn: bước 1 bỏ qua dòng đã đổi, bước 2 không trừ kho hai lần. Site không có ĐVT Can thì không làm gì.
"""

import frappe

from tracecore.inventory import consume, units

STOCK_UOM = "Can"
ML_PER_UNIT = 5000


def execute():
	if frappe.db.exists("UOM", STOCK_UOM):
		run(STOCK_UOM, ML_PER_UNIT)


def run(uom, ml_per_unit):
	units.convert_chemical_norms(uom, ml_per_unit, dry_run=False)
	for batch in frappe.get_all(
		"Notification Delivery",
		filters={"event_code": "CONSUMPTION_FAILED", "ref_doctype": "Wash Batch"},
		pluck="ref_name",
		distinct=True,
		order_by="ref_name asc",
	):
		if not frappe.db.exists("Wash Batch", batch):
			continue
		try:
			consume.retry("Wash Batch", batch)
		except frappe.ValidationError:
			frappe.log_error(title=f"chemical_norms_to_ml retry {batch}")
