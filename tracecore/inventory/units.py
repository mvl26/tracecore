"""Chuyển định mức hóa chất rửa sang ml mà không đổi ĐVT tồn kho (ticket T2 31/10/2026; A-72, FEAT-042).

Item đã có giao dịch kho thì ERPNext không cho đổi ĐVT gốc (Stock Ledger Entry), nên hóa chất vẫn nhập và tồn theo Can; chỉ
định mức trong `Process Program` khai theo ml và `consume` đổi về Can khi trừ kho. Hàm này làm ba việc, mỗi việc chạy lại
được (idempotent):

1. thêm dòng quy đổi ``ml`` vào bảng đơn vị tính của từng Item hóa chất tồn theo `uom`;
2. tắt "Phải là số nguyên" của `uom` (ảnh hưởng MỌI Item dùng chung đơn vị đó);
3. đổi các dòng `Program Consumable` của các Item đó sang ml (số lượng nhân tỷ lệ), chưa đổi thì mới đổi.

Chạy trên dữ liệu thật phải có backup và do người dùng duyệt từng lần::

    bench --site <site> execute tracecore.inventory.units.convert_chemical_norms --kwargs "{'uom': 'Can', 'ml_per_unit': 5000, 'dry_run': 1}"
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

SMALL_UOM = "ml"
CHEMICAL_GROUP = "Chemical"  # Item.tc_item_group_cssd của hóa chất rửa
QTY_FIELDS = ("qty_per_load", "qty_per_pack", "qty_per_kg")


def _chemical_items(uom):
	return sorted(
		frappe.get_all("Item", filters={"tc_item_group_cssd": CHEMICAL_GROUP, "stock_uom": uom}, pluck="name")
	)


def convert_chemical_norms(uom, ml_per_unit, dry_run=True):
	"""Chuyển định mức hóa chất tồn theo `uom` sang ml (1 `uom` = `ml_per_unit` ml). Trả báo cáo các thay đổi.

	``dry_run`` (mặc định bật) chỉ báo cáo, không ghi. Báo cáo: ``items``, ``conversions_added``, ``norm_rows``,
	``uom_freed`` và ``rows`` (từng dòng định mức: chương trình, vật tư, số cũ → số mới).
	"""
	ml_per_unit = flt(ml_per_unit)
	if ml_per_unit <= 0:
		frappe.throw(_("ml_per_unit must be greater than 0."))
	dry_run = cint(dry_run)
	items = _chemical_items(uom)
	report = {"items": items, "conversions_added": 0, "norm_rows": 0, "uom_freed": 0, "rows": []}
	if not dry_run and not frappe.db.exists("UOM", SMALL_UOM):
		frappe.get_doc({"doctype": "UOM", "uom_name": SMALL_UOM, "must_be_whole_number": 0}).insert(
			ignore_permissions=True
		)
	for item in items:
		if frappe.db.exists(
			"UOM Conversion Detail", {"parent": item, "parenttype": "Item", "uom": SMALL_UOM}
		):
			continue
		report["conversions_added"] += 1
		if not dry_run:
			doc = frappe.get_doc("Item", item)
			doc.flags.tc_legacy_data = True
			doc.append("uoms", {"uom": SMALL_UOM, "conversion_factor": 1 / ml_per_unit})
			doc.save(ignore_permissions=True)
	if frappe.db.get_value("UOM", uom, "must_be_whole_number"):
		report["uom_freed"] = 1
		if not dry_run:
			frappe.db.set_value("UOM", uom, "must_be_whole_number", 0)
			frappe.clear_cache(doctype="UOM")
	if items:
		for row in frappe.get_all(
			"Program Consumable",
			filters={"item": ["in", items], "uom": ["in", ["", None]]},
			fields=["name", "parent", "item", *QTY_FIELDS],
		):
			new = {field: flt(row[field] * ml_per_unit, 6) for field in QTY_FIELDS}
			report["norm_rows"] += 1
			report["rows"].append(
				{
					"program": row.parent,
					"item": row.item,
					"before": {field: row[field] for field in QTY_FIELDS},
					"after": new,
				}
			)
			if not dry_run:
				frappe.db.set_value(
					"Program Consumable", row.name, {"uom": SMALL_UOM, **new}, update_modified=False
				)
	return report
