"""Laundry Equipment Norms: định mức và thực tế theo ngày, máy, chương trình (#1847 DV-05; FR-M3-10; A-104 D10).

Một lô có sấy hiện ở cả dòng máy giặt và dòng máy sấy (mỗi máy phần của mình), nên không cộng số lô giữa các máy. Hóa chất
là ba cột động (định mức, thực tế, chênh lệch) theo từng vật tư có trong khoảng ngày.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from tracecore.linen import machine_usage


def _column(fieldname, label, fieldtype="Float", width=110, **extra):
	return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "width": width, **extra}


def _columns(items):
	columns = [
		_column("date", _("Date"), "Date", 100),
		_column("machine", _("Machine"), "Link", 130, options="Equipment"),
		_column("machine_type", _("Machine Type"), "Data", 110),
		_column("program", _("Program"), "Link", 140, options="Process Program"),
		_column("batches", _("Batches"), "Int", 70),
		_column("weight_kg", _("Weight (kg)")),
	]
	for index, item in enumerate(items):
		columns += [
			_column(f"chem_{index}_norm", _("{0} norm").format(item)),
			_column(f"chem_{index}_actual", _("{0} actual").format(item)),
			_column(f"chem_{index}_difference", _("{0} difference").format(item)),
		]
	money = {"precision": 0}
	return [
		*columns,
		_column("water_norm_m3", _("Water norm (m3)")),
		_column("water_actual_m3", _("Water actual (m3)")),
		_column("water_difference_m3", _("Water difference (m3)")),
		_column("power_norm", _("Power norm (kWh)")),
		_column("power_actual", _("Power actual (kWh)")),
		_column("power_difference", _("Power difference (kWh)")),
		_column("cost_norm", _("Norm cost"), "Currency", 130, **money),
		_column("cost_actual", _("Actual cost"), "Currency", 130, **money),
		_column("cost_difference", _("Cost difference"), "Currency", 130, **money),
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
	groups = {}
	for stage in machine_usage.stages(
		start, end, equipment=filters.get("equipment"), program=filters.get("program")
	):
		key = (stage["date"], stage["machine"], stage["program"] or "")
		group = groups.setdefault(
			key,
			{
				"date": stage["date"],
				"machine": stage["machine"],
				"program": stage["program"],
				**machine_usage.empty_total(),
			},
		)
		machine_usage.add(group, stage)
	items = sorted({item for group in groups.values() for item in group["chemicals"]})
	types = dict(
		frappe.get_all(
			"Equipment",
			filters={"name": ["in", [key[1] for key in groups] or [""]]},
			fields=["name", "equipment_type"],
			as_list=True,
		)
	)
	rows = []
	for key in sorted(groups):
		rows.append(_row(machine_usage.finish(groups[key]), items, types))
	return _columns(items), rows


def _row(group, items, types):
	chemicals = group.pop("chemicals")
	row = {
		**group,
		"machine_type": _(types.get(group["machine"]) or "", context="Equipment"),
		"water_difference_m3": flt(group["water_actual_m3"] - group["water_norm_m3"], 3),
		"power_difference": flt(group["power_actual"] - group["power_norm"], 3),
		"cost_difference": flt(group["cost_actual"] - group["cost_norm"], 2),
	}
	for index, item in enumerate(items):
		chemical = chemicals.get(item)
		if chemical:
			row[f"chem_{index}_norm"] = flt(chemical["norm"], 3)
			row[f"chem_{index}_actual"] = flt(chemical["actual"], 3)
			row[f"chem_{index}_difference"] = flt(chemical["actual"] - chemical["norm"], 3)
	return row
