"""Định mức theo mẻ của chương trình giặt/sấy, đổi sang ĐVT tồn kho (#1847, FR-M3-08, A-104).

Dùng chung cho M3 (`linen.laundry`, ghi số định mức vào lô) và M7 (`costing.from_laundry`, tính tiền): hai phân hệ không import
nhau nên phần đọc `Process Program` đặt ở core. Chỉ đọc, không ghi.
"""

import frappe
from frappe.utils import flt

PRECISION = 6


def stock_factor(item, uom):
	"""Hệ số đổi `uom` sang ĐVT tồn kho của `item`; 1 khi cùng đơn vị hoặc chưa khai quy đổi (Process Program đã chặn khi lưu)."""
	if not uom or uom == frappe.db.get_value("Item", item, "stock_uom"):
		return 1
	factor = frappe.db.get_value(
		"UOM Conversion Detail", {"parent": item, "parenttype": "Item", "uom": uom}, "conversion_factor"
	)
	return flt(factor) or 1


def of(program, kg):
	"""Định mức của `program` cho một mẻ `kg` kg: ``{program, kwh, water_l, minutes, lines}``.

	``lines`` = ``[{item, program, uom, qty, unit_price}]``, ``qty`` theo ĐVT tồn kho = (mỗi lô + mỗi kg x kg) x hệ số đổi.
	"""
	row = frappe.db.get_value(
		"Process Program", program, ["kwh_per_cycle", "water_l_per_cycle", "duration_min"], as_dict=True
	)
	lines = []
	for norm in frappe.get_all(
		"Program Consumable",
		filters={"parent": program, "parenttype": "Process Program"},
		fields=["item", "uom", "qty_per_load", "qty_per_kg", "unit_price"],
		order_by="idx",
	):
		qty = (flt(norm.qty_per_load) + flt(norm.qty_per_kg) * flt(kg)) * stock_factor(norm.item, norm.uom)
		lines.append(
			{
				"item": norm.item,
				"program": program,
				"uom": frappe.db.get_value("Item", norm.item, "stock_uom"),
				"qty": flt(qty, PRECISION),
				"unit_price": flt(norm.unit_price),
			}
		)
	return {
		"program": program,
		"kwh": flt(row.kwh_per_cycle) if row else 0,
		"water_l": flt(row.water_l_per_cycle) if row else 0,
		"minutes": flt(row.duration_min) if row else 0,
		"lines": lines,
	}


def reference_kg(program):
	"""Tải tính định mức/kg của chương trình: tải tối đa của chương trình, không có thì tải máy; 0 khi chưa khai."""
	row = frappe.db.get_value("Process Program", program, ["max_load_kg", "equipment"], as_dict=True)
	if not row:
		return 0
	return flt(row.max_load_kg) or flt(frappe.db.get_value("Equipment", row.equipment, "capacity_kg"))
