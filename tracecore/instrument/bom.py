"""BOM của loại bộ theo phiên bản (Set BOM Item, DT-SETBOM): đọc dòng BOM kèm tên và ảnh dụng cụ."""

import frappe
from frappe.utils import cint

from tracecore.instrument import bom_versions

TRAY_FIELDS = ("tray_image", "tray_image_2", "tray_image_3")  # ảnh bộ đã xếp 1..3 (FEAT-015 S6)


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
	"""Hook ``tracecore_pack_context`` (FEAT-018 D9): BOM áp dụng của bộ và ảnh khay của loại bộ cho màn T4.

	Phiên bản = ``bom_versions.version_for_set_unit(ctx["set_unit"])``: bộ đang trong chu trình giữ phiên bản đã ghim
	khi tiếp nhận, kể cả khi có phiên bản mới hiệu lực giữa chu trình (FR-M1-04.1, FEAT-015 S3). Chỉ đọc, không ghi.
	Trả ``{"bom": [dòng của lines()], "bom_version": int, "tray_image": str | None, "tray_images": [str, …]}``
	(``tray_image`` = ảnh 1 như FEAT-018; ``tray_images`` = các ảnh 1..3 có giá trị theo thứ tự).
	Ngữ cảnh không có ``set_unit`` (chỉ loại bộ, vd xem trước) → ``set_type["current_bom_version"]`` như FEAT-018.
	"""
	set_type = ctx["set_type"]
	if ctx.get("set_unit"):
		version = cint(bom_versions.version_for_set_unit(ctx["set_unit"]))
	else:
		version = cint(set_type.get("current_bom_version"))
	images = frappe.db.get_value("Instrument Set Type", set_type["name"], TRAY_FIELDS, as_dict=True) or {}
	return {
		"bom": lines(set_type["name"], version),
		"bom_version": version,
		"tray_image": set_type.get("tray_image") or None,
		"tray_images": [images.get(field) for field in TRAY_FIELDS if images.get(field)],
	}
