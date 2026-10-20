"""BOM của loại bộ theo phiên bản (Set BOM Item, DT-SETBOM): đọc dòng BOM kèm tên và ảnh dụng cụ."""

import frappe
from frappe.utils import cint


def lines(set_type, version):
	"""Các dòng BOM của `set_type` ở phiên bản `version`, sắp theo `position` (hòa thì theo `name`).

	Mỗi dòng là dict: ``instrument, instrument_name, image, qty, position``.
	"""
	rows = frappe.get_all(
		"Set BOM Item",
		filters={"set_type": set_type, "bom_version": cint(version)},
		fields=["name", "instrument", "qty", "position"],
		order_by="position asc, name asc",
	)
	if not rows:
		return []
	instruments = {
		row.name: row
		for row in frappe.get_all(
			"Instrument",
			filters={"name": ["in", list({row.instrument for row in rows})]},
			fields=["name", "instrument_name", "image"],
		)
	}
	return [
		{
			"instrument": row.instrument,
			"instrument_name": instruments[row.instrument].instrument_name,
			"image": instruments[row.instrument].image,
			"qty": cint(row.qty),
			"position": cint(row.position),
		}
		for row in rows
	]
