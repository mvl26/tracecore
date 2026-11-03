"""Consumable Usage: định mức so với thực dùng của vật tư theo kỳ, máy, công đoạn, loại test (A-112 D12; FR-M6-07).

Nguồn là dòng `Run Consumable` (A-111) của lô rửa, mẻ tiệt khuẩn chưa hủy và test đầu ngày đã ghi kết quả. Dữ liệu trước
A-111 không có dòng vật tư nên không có trong báo cáo. Công đoạn suy theo `inventory.usage.stage`.
"""

from collections import defaultdict
from datetime import date

import frappe
from frappe import _
from frappe.utils import flt, getdate

from tracecore.inventory import usage

PRECISION = 6
DAY, MONTH = "Day", "Month"
# (DocType nguồn, cột ngày, cột loại lô, điều kiện đã dùng vật tư)
SOURCES = (
	("Wash Batch", "started_at", "batch_type", "parent.docstatus < 2"),
	("Sterilization Load", "started_at", None, "parent.docstatus < 2"),
	("Daily Test", "started_at", None, "ifnull(parent.result, '') != ''"),
)


def _columns():
	return [
		{"fieldname": "period", "label": _("Period"), "fieldtype": "Data", "width": 100},
		{
			"fieldname": "equipment",
			"label": _("Machine"),
			"fieldtype": "Link",
			"options": "Equipment",
			"width": 110,
		},
		{"fieldname": "equipment_name", "label": _("Equipment Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "stage", "label": _("Stage"), "fieldtype": "Data", "width": 110},
		{"fieldname": "test_type", "label": _("Test Type"), "fieldtype": "Data", "width": 110},
		{"fieldname": "item", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 140},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 190},
		{"fieldname": "role", "label": _("Role"), "fieldtype": "Data", "width": 120},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 70},
		{"fieldname": "runs", "label": _("Runs"), "fieldtype": "Int", "width": 70},
		{"fieldname": "norm_qty", "label": _("Norm"), "fieldtype": "Float", "width": 90},
		{"fieldname": "actual_qty", "label": _("Actual"), "fieldtype": "Float", "width": 90},
		{"fieldname": "variance", "label": _("Variance"), "fieldtype": "Float", "width": 90},
		{"fieldname": "variance_pct", "label": _("Variance %"), "fieldtype": "Percent", "width": 90},
	]


def _rows(doctype, date_field, type_field, used, filters):
	conditions = [used]
	values = {"doctype": doctype}
	if filters.get("from_date"):
		conditions.append(f"date(parent.{date_field}) >= %(from_date)s")
		values["from_date"] = getdate(filters["from_date"])
	if filters.get("to_date"):
		conditions.append(f"date(parent.{date_field}) <= %(to_date)s")
		values["to_date"] = getdate(filters["to_date"])
	for field in ("equipment", "item", "role"):
		if filters.get(field):
			column = "parent.equipment" if field == "equipment" else f"rc.{field}"
			conditions.append(f"{column} = %({field})s")
			values[field] = filters[field]
	batch_type = f"parent.{type_field}" if type_field else "null"
	return frappe.db.sql(
		f"""
		select rc.parent, rc.item, rc.item_name, rc.role, rc.uom, rc.norm_qty, rc.actual_qty,
			date(parent.{date_field}) as run_date, parent.equipment, {batch_type} as batch_type,
			eq.equipment_name, eq.equipment_type, pp.program_kind, pp.daily_test_type
		from `tabRun Consumable` rc
		join `tab{doctype}` parent on parent.name = rc.parent
		left join `tabEquipment` eq on eq.name = parent.equipment
		left join `tabProcess Program` pp on pp.name = parent.program
		where rc.parenttype = %(doctype)s and {" and ".join(conditions)}
		""",  # nosec B608 - tên bảng/cột và điều kiện ghép từ hằng SOURCES, giá trị lọc qua tham số
		values,
		as_dict=True,
	)


def _period(run_date, group_by):
	"""``(ngày đầu kỳ để sắp xếp, nhãn kỳ dd/mm/yyyy hoặc mm/yyyy)``."""
	if not run_date:
		return None, ""
	if group_by == MONTH:
		return run_date.replace(day=1), run_date.strftime("%m/%Y")
	return run_date, run_date.strftime("%d/%m/%Y")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	group_by = DAY if filters.get("group_by") == DAY else MONTH
	groups = {}
	runs = defaultdict(set)
	for doctype, date_field, type_field, used in SOURCES:
		for row in _rows(doctype, date_field, type_field, used, filters):
			stage = usage.stage(row.equipment_type, row.program_kind, row.batch_type)
			test_type = row.daily_test_type if stage == usage.TEST else None
			if filters.get("stage") and stage != filters["stage"]:
				continue
			if filters.get("test_type") and test_type != filters["test_type"]:
				continue
			start, label = _period(row.run_date, group_by)
			key = (start, row.equipment, stage, test_type, row.item, row.role)
			group = groups.setdefault(
				key,
				{
					"period": label,
					"equipment": row.equipment,
					"equipment_name": row.equipment_name,
					"stage": stage,
					"test_type": test_type,
					"item": row.item,
					"item_name": row.item_name,
					"role": row.role,
					"uom": row.uom,
					"norm_qty": 0,
					"actual_qty": 0,
				},
			)
			group["norm_qty"] = flt(group["norm_qty"] + flt(row.norm_qty), PRECISION)
			group["actual_qty"] = flt(group["actual_qty"] + flt(row.actual_qty), PRECISION)
			runs[key].add((doctype, row.parent))
	data = []
	ordered = sorted(
		groups.items(),
		key=lambda pair: (pair[0][0] or date.min, pair[1]["equipment_name"] or "", pair[1]["item"]),
	)
	for key, group in ordered:
		variance = flt(group["actual_qty"] - group["norm_qty"], PRECISION)
		data.append(
			{
				**group,
				"runs": len(runs[key]),
				"variance": variance,
				"variance_pct": flt(variance * 100 / group["norm_qty"], 2) if group["norm_qty"] else None,
			}
		)
	return _columns(), data
