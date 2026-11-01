"""Sử dụng theo máy giặt, máy sấy từ các lô đã ghi sổ (#1847 DV-04, DV-05; FR-M3-10; A-104 D10).

Mỗi lô tự giặt thành một "chặng" máy giặt và, nếu có sấy, một chặng máy sấy. Điện chia theo kWh của từng máy, nước và nhân công
về máy giặt, hóa chất theo chương trình của dòng; nên tổng chi phí hai chặng bằng chi phí của lô. Chỉ đọc, qua `frappe.get_list`
nên chịu quyền của người xem.
"""

import frappe
from frappe.utils import flt, getdate

DOCTYPE = "Laundry Batch"
IN_HOUSE = "In-house"
LITRES_PER_M3 = 1000
HISTORY_LIMIT = 200
BATCH_FIELDS = (
	"name status ended_at weight_kg equipment program dryer dry_program norm_kwh actual_kwh norm_dry_kwh actual_dry_kwh "
	"norm_water_l actual_water_l cost_electricity cost_water cost_labor cost_total cost_per_kg norm_cost_electricity "
	"norm_cost_water norm_cost_total"
).split()


def _batches(start, end):
	return frappe.get_list(
		DOCTYPE,
		filters={
			"docstatus": 1,
			"batch_type": IN_HOUSE,
			"ended_at": ["between", [f"{getdate(start)} 00:00:00", f"{getdate(end)} 23:59:59"]],
		},
		fields=BATCH_FIELDS,
		order_by="ended_at asc",
		limit_page_length=0,
	)


def _rows_by_batch(names):
	rows = {}
	if not names:
		return rows
	for row in frappe.get_all(
		"Laundry Batch Chemical",
		filters={"parent": ["in", names], "parenttype": DOCTYPE},
		fields=["parent", "item", "program", "uom", "qty", "norm_qty", "unit_price", "amount"],
		order_by="idx",
	):
		rows.setdefault(row.parent, []).append(row)
	return rows


def _share(total_cost, part, total):
	return flt(total_cost) * flt(part) / flt(total) if flt(total) else 0


def _stage(batch, rows, machine, program, dryer):
	"""Một chặng của lô trên `machine`; ``dryer`` phân biệt phần điện, nước, nhân công và dòng hóa chất."""
	total_actual = flt(batch.actual_kwh) + flt(batch.actual_dry_kwh)
	total_norm = flt(batch.norm_kwh) + flt(batch.norm_dry_kwh)
	power_actual = flt(batch.actual_dry_kwh if dryer else batch.actual_kwh)
	power_norm = flt(batch.norm_dry_kwh if dryer else batch.norm_kwh)
	if dryer:
		lines = [row for row in rows if batch.dry_program and row.program == batch.dry_program]
	else:
		lines = [row for row in rows if not (batch.dry_program and row.program == batch.dry_program)]
	cost_actual = _share(batch.cost_electricity, power_actual, total_actual) + sum(
		flt(row.amount) for row in lines
	)
	cost_norm = _share(batch.norm_cost_electricity, power_norm, total_norm) + sum(
		flt(row.norm_qty) * flt(row.unit_price) for row in lines
	)
	if not dryer:
		cost_actual += flt(batch.cost_water) + flt(batch.cost_labor)
		cost_norm += flt(batch.norm_cost_water) + flt(batch.cost_labor)
	return {
		"date": getdate(batch.ended_at),
		"machine": machine,
		"program": program,
		"weight_kg": flt(batch.weight_kg),
		"power_norm": power_norm,
		"power_actual": power_actual,
		"water_norm_l": 0 if dryer else flt(batch.norm_water_l),
		"water_actual_l": 0 if dryer else flt(batch.actual_water_l),
		"cost_norm": cost_norm,
		"cost_actual": cost_actual,
		"lines": lines,
	}


def stages(start, end, equipment=None, program=None):
	"""Các chặng trong khoảng ngày, lọc theo máy và chương trình."""
	batches = _batches(start, end)
	rows = _rows_by_batch([batch.name for batch in batches])
	found = []
	for batch in batches:
		lines = rows.get(batch.name, [])
		candidates = [_stage(batch, lines, batch.equipment, batch.program, False)]
		if batch.dryer:
			candidates.append(_stage(batch, lines, batch.dryer, batch.dry_program, True))
		found += [
			stage
			for stage in candidates
			if (not equipment or stage["machine"] == equipment)
			and (not program or stage["program"] == program)
		]
	return found


def empty_total():
	return {
		"batches": 0,
		"weight_kg": 0,
		"power_norm": 0,
		"power_actual": 0,
		"water_norm_l": 0,
		"water_actual_l": 0,
		"cost_norm": 0,
		"cost_actual": 0,
		"chemicals": {},
	}


def add(total, stage):
	"""Cộng một chặng vào `total`; hóa chất theo mã vật tư."""
	total["batches"] += 1
	for field in (
		"weight_kg",
		"power_norm",
		"power_actual",
		"water_norm_l",
		"water_actual_l",
		"cost_norm",
		"cost_actual",
	):
		total[field] += stage[field]
	for line in stage["lines"]:
		chemical = total["chemicals"].setdefault(
			line.item, {"item": line.item, "uom": line.uom, "norm": 0, "actual": 0, "amount": 0}
		)
		chemical["norm"] += flt(line.norm_qty)
		chemical["actual"] += flt(line.qty)
		chemical["amount"] += flt(line.amount)
	return total


def finish(total):
	"""Làm tròn số thập phân cộng dồn; nước đổi sang m³."""
	total["water_norm_m3"] = flt(total.pop("water_norm_l") / LITRES_PER_M3, 3)
	total["water_actual_m3"] = flt(total.pop("water_actual_l") / LITRES_PER_M3, 3)
	for field in ("weight_kg", "power_norm", "power_actual"):
		total[field] = flt(total[field], 3)
	for field in ("cost_norm", "cost_actual"):
		total[field] = flt(total[field], 2)
	return total


def usage(equipment, start, end):
	"""Khối Sử dụng trên form máy (DV-04): theo ngày và chương trình, tổng, từng hóa chất, lịch sử lô."""
	found = stages(start, end, equipment=equipment)
	days, totals = {}, empty_total()
	for stage in found:
		key = (stage["date"], stage["program"] or "")
		add(
			days.setdefault(key, {"date": stage["date"], "program": stage["program"], **empty_total()}), stage
		)
		add(totals, stage)
	chemicals = sorted(totals.pop("chemicals").values(), key=lambda row: row["item"])
	day_rows = []
	for key in sorted(days):
		row = finish(days[key])
		row.pop("chemicals")
		day_rows.append(row)
	return {
		"totals": finish(totals),
		"days": day_rows,
		"chemicals": chemicals,
		"history": _history(equipment, start, end),
	}


def _history(equipment, start, end):
	return frappe.get_list(
		DOCTYPE,
		filters={
			"docstatus": 1,
			"batch_type": IN_HOUSE,
			"ended_at": ["between", [f"{getdate(start)} 00:00:00", f"{getdate(end)} 23:59:59"]],
		},
		or_filters={"equipment": equipment, "dryer": equipment},
		fields=[
			"name",
			"ended_at",
			"status",
			"weight_kg",
			"program",
			"dry_program",
			"cost_total",
			"cost_per_kg",
		],
		order_by="ended_at desc",
		limit_page_length=HISTORY_LIMIT,
	)
