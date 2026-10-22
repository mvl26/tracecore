"""BOM của loại bộ theo phiên bản (Set BOM Item, DT-SETBOM): đọc dòng BOM kèm tên và ảnh dụng cụ."""

import frappe
from frappe.utils import cint


def lines(set_type, version):
	"""Các dòng BOM của `set_type` ở phiên bản `version`, sắp theo `position` (hòa thì theo `name`).

	Mỗi dòng là dict: ``instrument, instrument_name, image, thumbnail, qty, position`` (``thumbnail`` = URL ảnh
	thu nhỏ 320 px cho trạm, FR-M1-01.6; None khi chưa có).
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
			fields=["name", "instrument_name", "image", "image_thumbnail"],
		)
	}
	return [
		{
			"instrument": row.instrument,
			"instrument_name": instruments[row.instrument].instrument_name,
			"image": instruments[row.instrument].image,
			"thumbnail": instruments[row.instrument].image_thumbnail or None,
			"qty": cint(row.qty),
			"position": cint(row.position),
		}
		for row in rows
	]


def pack_context(ctx):
	"""Hook ``tracecore_pack_context`` (FEAT-018 D9): BOM hiện hành và ảnh khay của loại bộ cho màn T4.

	Đọc ``ctx["set_type"]`` (``name``, ``current_bom_version``, ``tray_image``); chỉ đọc, không ghi.
	Trả ``{"bom": [dòng của lines()], "bom_version": int, "tray_image": str | None}``.
	"""
	set_type = ctx["set_type"]
	version = cint(set_type.get("current_bom_version"))
	return {
		"bom": lines(set_type["name"], version),
		"bom_version": version,
		"tray_image": set_type.get("tray_image") or None,
	}
