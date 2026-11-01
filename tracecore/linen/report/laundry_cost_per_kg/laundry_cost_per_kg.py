"""Laundry Cost per Kg: chi phí/kg của lô giặt theo tháng hoàn tất (FEAT-034; FR-M3-04.1; A-50 D12).

Chỉ lô đã ghi sổ (Đạt hoặc Không đạt); lô đang chạy và lô đã hủy không tính. Chi phí/kg của tháng là tổng chi phí chia tổng kg
(bình quân gia quyền theo kg), không phải trung bình các chi phí/kg của từng lô. Lô thiếu giá khi tính (có ghi chú chi phí)
được đếm riêng để người đọc biết con số chưa đủ.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from tracecore.linen.laundry import DOCTYPE


def _columns(machine_detail=False):
	machine = (
		[{"fieldname": "machine", "label": _("Machine"), "fieldtype": "Data", "width": 150}]
		if machine_detail
		else []
	)
	return [
		{"fieldname": "month", "label": _("Month"), "fieldtype": "Data", "width": 100},
		*machine,
		{"fieldname": "batches", "label": _("Batches"), "fieldtype": "Int", "width": 90},
		{"fieldname": "weight_kg", "label": _("Weight (kg)"), "fieldtype": "Float", "width": 120},
		{
			"fieldname": "cost_total",
			"label": _("Total Cost"),
			"fieldtype": "Currency",
			"precision": 0,
			"width": 140,
		},
		{
			"fieldname": "cost_per_kg",
			"label": _("Cost per kg"),
			"fieldtype": "Currency",
			"precision": 0,
			"width": 130,
		},
		{"fieldname": "without_rate", "label": _("Batches without a rate"), "fieldtype": "Int", "width": 170},
	]


def _dates(filters):
	if not (filters.get("from_date") and filters.get("to_date")):
		frappe.throw(_("From Date and To Date are required."))
	start, end = getdate(filters.from_date), getdate(filters.to_date)
	if end < start:
		frappe.throw(_("To Date cannot be before From Date."))
	return start, end


def execute(filters=None):
	filters = frappe._dict(filters or {})
	start, end = _dates(filters)
	batches = frappe.get_list(
		DOCTYPE,
		filters={"docstatus": 1, "ended_at": ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]]},
		fields=["ended_at", "weight_kg", "cost_total", "cost_note", "equipment", "batch_type"],
		order_by="ended_at asc",
	)
	months, machines = {}, {}
	for batch in batches:
		month = batch.ended_at.strftime("%Y-%m")
		_add(months.setdefault(month, _empty()), batch)
		machine = batch.equipment or _("Outsourced batches")
		_add(machines.setdefault(month, {}).setdefault(machine, _empty()), batch)
	detail = cint(filters.get("machine_detail"))
	rows = []
	for month, row in sorted(months.items()):
		rows.append(_result(row, month=month))
		if detail:
			rows += [
				_result(cells, month=month, machine=machine)
				for machine, cells in sorted(machines[month].items())
			]
	return _columns(bool(detail)), rows


def _empty():
	return {"batches": 0, "weight_kg": 0, "cost_total": 0, "without_rate": 0}


def _add(row, batch):
	row["batches"] += 1
	row["weight_kg"] += flt(batch.weight_kg)
	row["cost_total"] += flt(batch.cost_total)
	row["without_rate"] += 1 if batch.cost_note else 0


def _result(row, **keys):
	return {
		**keys,
		**row,
		"cost_per_kg": round(row["cost_total"] / row["weight_kg"]) if row["weight_kg"] else 0,
		"without_rate": cint(row["without_rate"]),
	}
