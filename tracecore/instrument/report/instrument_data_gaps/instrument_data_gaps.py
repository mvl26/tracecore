"""Instrument Data Gaps (FR-M1-01.2, A-06 I4): dụng cụ cần bổ sung dữ liệu.

Một dòng cho mỗi dụng cụ (mặc định Đang dùng) thiếu ít nhất một thứ: cơ số tối đa (Chưa xác định), ảnh, IFU,
phân loại Spaulding hoặc phương pháp tương thích (dụng cụ có từ trước FEAT-014). Cột thiếu ghi chữ, cột đủ để trống.
"""

import frappe
from frappe import _
from frappe.utils import cint

DEFAULT_STATUS = "Active"


def _columns():
	return [
		{
			"fieldname": "instrument",
			"label": _("Instrument Code"),
			"fieldtype": "Link",
			"options": "Instrument",
			"width": 150,
		},
		{"fieldname": "instrument_name", "label": _("Instrument Name"), "fieldtype": "Data", "width": 220},
		{
			"fieldname": "instrument_group",
			"label": _("Instrument Group"),
			"fieldtype": "Link",
			"options": "Instrument Group",
			"width": 150,
		},
		{"fieldname": "max_cycles", "label": _("Max Cycles"), "fieldtype": "Data", "width": 130},
		{"fieldname": "image", "label": _("Image"), "fieldtype": "Data", "width": 110},
		{"fieldname": "ifu", "label": _("IFU"), "fieldtype": "Data", "width": 110},
		{"fieldname": "spaulding_class", "label": _("Spaulding Class"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "compatible_methods",
			"label": _("Compatible Methods"),
			"fieldtype": "Data",
			"width": 160,
		},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions = {"status": filters.get("status") or DEFAULT_STATUS}
	if filters.get("instrument_group"):
		conditions["instrument_group"] = filters.instrument_group
	instruments = frappe.get_list(
		"Instrument",
		filters=conditions,
		fields=[
			"name",
			"instrument_name",
			"instrument_group",
			"max_cycles",
			"image",
			"ifu",
			"spaulding_class",
		],
		order_by="name asc",
	)
	names = [row.name for row in instruments]
	with_methods = (
		set(
			frappe.get_all(
				"Instrument Compatible Method",
				filters={
					"parenttype": "Instrument",
					"parentfield": "compatible_methods",
					"parent": ["in", names],
				},
				pluck="parent",
			)
		)
		if names
		else set()
	)
	undefined, missing = _("Undefined"), _("Not provided")
	data = []
	for row in instruments:
		gaps = {
			"max_cycles": undefined if cint(row.max_cycles) <= 0 else "",
			"image": "" if row.image else missing,
			"ifu": "" if row.ifu else missing,
			"spaulding_class": "" if row.spaulding_class else missing,
			"compatible_methods": "" if row.name in with_methods else missing,
		}
		if any(gaps.values()):
			data.append(
				{
					"instrument": row.name,
					"instrument_name": row.instrument_name,
					"instrument_group": row.instrument_group,
					**gaps,
				}
			)
	return _columns(), data
