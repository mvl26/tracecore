"""Cost by Target: chi phí theo thiết bị, khu hoặc chương trình và kỳ (FEAT-044; FR-M7-02.3; UC-27 bước 5; A-47 C11).

Mỗi khoản `Cost Entry` đã ghi sổ có kỳ giao với khoảng ngày lọc được chia theo ngày (`costing.entry.split`) rồi theo tỷ lệ
phân bổ; một dòng cho mỗi (đối tượng, khoản mục). Nháp và khoản đã Hủy không tính.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from tracecore.costing import entry as costing


def _columns():
	return [
		{"fieldname": "target_type", "label": _("Target Type"), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "target",
			"label": _("Target", context="Cost Entry"),
			"fieldtype": "Dynamic Link",
			"options": "target_type",
			"width": 200,
		},
		{
			"fieldname": "category",
			"label": _("Category", context="Cost Entry"),
			"fieldtype": "Link",
			"options": "Cost Category",
			"width": 180,
		},
		{
			"fieldname": "amount",
			"label": _("Amount", context="Cost Entry"),
			"fieldtype": "Currency",
			"precision": 0,
			"width": 160,
		},
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
	conditions = {"docstatus": 1, "period_from": ["<=", end], "period_to": [">=", start]}
	if filters.get("category"):
		conditions["category"] = filters.category
	totals = {}
	for name in frappe.get_list("Cost Entry", filters=conditions, pluck="name"):
		entry = frappe.get_doc("Cost Entry", name)
		for (target_type, target), amount in costing.split(entry, start, end).items():
			if filters.get("target_type") and filters.target_type != target_type:
				continue
			if filters.get("target") and filters.target != target:
				continue
			key = (target_type, target, entry.category)
			totals[key] = totals.get(key, 0) + amount
	rows = [
		{"target_type": target_type, "target": target, "category": category, "amount": amount}
		for (target_type, target, category), amount in sorted(totals.items())
		if amount
	]
	summary = [
		{
			# ô tổng của Frappe không nhận precision nên Currency luôn có phần lẻ; VND không lẻ → số nguyên kèm đơn vị
			"label": _("Total Cost (VND)"),
			"value": sum(cint(row["amount"]) for row in rows),
			"datatype": "Int",
			"indicator": "blue",
		}
	]
	return _columns(), rows, None, None, summary
