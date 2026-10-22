"""Hạn lưu theo loại gói và ghi đè của loại bộ (M1, FEAT-015; FR-M1-03.4, FR-M1-03.5, BRU-REP-009, A-02 D4).

Hạn loại gói = ``Item.tc_shelf_life_days`` của Item nhóm ``Packaging`` còn dùng (A-02); **không có mặc định cứng**
(CHG-020). ``Instrument Set Type.shelf_life_days`` là ghi đè: 0 = dùng hạn loại gói, chỉ nhận giá trị ngắn hơn hạn
loại gói mặc định. Công thức hạn áp dụng = min(hạn loại gói, ghi đè > 0) như ``packing.compute_expiry`` của M2
(D4); M1 không import M2 (lint R1) nên tiêu chí được viết lại ở đây và test đối chiếu với M2 giữ hai bên khớp.
"""

import frappe
from frappe import _
from frappe.utils import cint

DOCTYPE = "Instrument Set Type"
PACKAGING = "Packaging"
SOURCE_PACK_TYPE = "Pack Type"
SOURCE_SET_TYPE = "Set Type"


def _pack_type_problem(item: str | None) -> tuple[str | None, int | None]:
	"""``(lý do không dùng được | None, hạn lưu | None)`` của loại gói `item` — cùng tiêu chí ``packing._pack_type_days``."""
	if not item:
		return _("No pack type was chosen."), None
	row = frappe.db.get_value(
		"Item", item, ["tc_item_group_cssd", "tc_shelf_life_days", "disabled"], as_dict=True
	)
	if not row or row.tc_item_group_cssd != PACKAGING:
		return _("{0} is not a packaging item, so it cannot be chosen as the pack type.").format(item), None
	if cint(row.disabled):
		return _("Pack type {0} is disabled and cannot be chosen.").format(item), None
	if cint(row.tc_shelf_life_days) <= 0:
		return _("Pack type {0} has no shelf life yet and cannot be chosen.").format(item), None
	return None, cint(row.tc_shelf_life_days)


def pack_type_days(item: str | None) -> int | None:
	"""Hạn lưu (ngày) của loại gói `item`; None khi không phải Packaging, đã ngừng dùng hoặc hạn lưu ≤ 0."""
	return _pack_type_problem(item)[1]


def usable_pack_types() -> list[dict]:
	"""Loại gói chọn được: Item Packaging còn dùng có hạn lưu > 0 (cùng bộ lọc ``packing.pack_types``), theo tên.

	Mỗi phần tử ``{"item", "item_name", "shelf_life_days"}``.
	"""
	rows = frappe.get_all(
		"Item",
		filters={"tc_item_group_cssd": PACKAGING, "disabled": 0, "tc_shelf_life_days": [">", 0]},
		fields=["name", "item_name", "tc_shelf_life_days"],
		order_by="item_name asc, name asc",
	)
	return [
		{"item": row.name, "item_name": row.item_name, "shelf_life_days": cint(row.tc_shelf_life_days)}
		for row in rows
	]


def _header(set_type_or_doc) -> dict:
	if isinstance(set_type_or_doc, str):
		row = frappe.db.get_value(
			DOCTYPE, set_type_or_doc, ["default_pack_type", "shelf_life_days"], as_dict=True
		)
		return row or {}
	return {
		"default_pack_type": set_type_or_doc.get("default_pack_type"),
		"shelf_life_days": set_type_or_doc.get("shelf_life_days"),
	}


def effective(set_type_or_doc, pack_type: str | None = None) -> dict:
	"""Hạn lưu áp dụng cho loại bộ (tên hoặc doc) với `pack_type` (mặc định: loại gói mặc định của loại bộ).

	Trả ``{"days", "source", "pack_type_days", "override"}``: ``source`` ``"Set Type"`` khi ghi đè > 0 và ngắn hơn
	hạn loại gói, ngược lại ``"Pack Type"``. Loại gói không dùng được → ``days``/``source``/``pack_type_days`` None
	(không bịa số ngày).
	"""
	header = _header(set_type_or_doc)
	override = cint(header.get("shelf_life_days"))
	days = pack_type_days(pack_type or header.get("default_pack_type"))
	result = {"days": None, "source": None, "pack_type_days": days, "override": override}
	if days is None:
		return result
	if 0 < override < days:
		result.update(days=override, source=SOURCE_SET_TYPE)
	else:
		result.update(days=days, source=SOURCE_PACK_TYPE)
	return result


def _changed(doc, *fields) -> bool:
	if doc.is_new():
		return True
	before = doc.get_doc_before_save()
	if before is None:
		return True
	return any(before.get(field) != doc.get(field) for field in fields)


def validate_set_type(doc) -> None:
	"""Luật loại gói / hạn lưu của loại bộ khi lưu (FR-M1-03.4, FR-M1-03.5).

	Chỉ kiểm khi tạo mới hoặc khi đổi loại gói / ghi đè: loại bộ cũ có loại gói sau này thôi dùng vẫn sửa được các
	trường khác (T4 tự chặn khi đóng gói). Loại gói trống để kiểm trường bắt buộc của Frappe báo.
	"""
	override = cint(doc.get("shelf_life_days"))
	if override < 0:
		frappe.throw(_("Shelf life override cannot be negative."))
	if not doc.get("default_pack_type") or not _changed(doc, "default_pack_type", "shelf_life_days"):
		return
	problem, days = _pack_type_problem(doc.default_pack_type)
	if problem:
		frappe.throw(problem, title=_("Pack type cannot be chosen"))
	if override and override >= days:
		frappe.throw(
			_(
				"The set type can only override the shelf life with a value shorter than {0} days, the shelf life of pack type {1}. Enter 0 to use the pack type shelf life."
			).format(days, doc.default_pack_type),
			title=_("Shelf life override not allowed"),
		)
