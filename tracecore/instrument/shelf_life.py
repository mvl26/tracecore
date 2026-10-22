"""Hạn lưu theo loại gói và ghi đè của loại bộ (M1, FEAT-015; FR-M1-03.4, FR-M1-03.5, BRU-REP-009, A-02 D4).

Hạn loại gói = ``Item.tc_shelf_life_days`` của Item nhóm ``Packaging`` còn dùng (A-02); **không có mặc định cứng**
(CHG-020). ``Instrument Set Type.shelf_life_days`` là ghi đè: 0 = dùng hạn loại gói, chỉ nhận giá trị ngắn hơn hạn
loại gói mặc định. Công thức hạn áp dụng = min(hạn loại gói, ghi đè > 0) như ``packing.compute_expiry`` của M2
(D4); M1 không import M2 (lint R1) nên tiêu chí được viết lại ở đây và test đối chiếu với M2 giữ hai bên khớp.

Sửa hạn loại gói (FR-M2-07.8, S7): ``set_pack_shelf_life`` (RPC ``v1.set_type_admin.set_pack_shelf_life`` cho TC R02,
TC R10, System Manager) có lý do bắt buộc và Audit Log ``Update`` trên Item. Pack đã đóng giữ snapshot
``shelf_life_days_applied``/``expiry`` (FEAT-018) nên giá trị mới chỉ áp cho gói đóng sau. Đổi hạn lưu qua form Item
cũng ghi Audit Log (``audit_item_change``, không chặn). Giảm hạn loại gói xuống ≤ ghi đè của loại bộ không bị chặn,
chỉ trả danh sách loại bộ có ghi đè thành vô hiệu theo ``min`` (``affected_set_types``).
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import audit
from tracecore.core.errors import Block, BlockedError
from tracecore.instrument.bom_versions import REASON_MAX, whole_number

DOCTYPE = "Instrument Set Type"
ITEM = "Item"
PACKAGING = "Packaging"
SOURCE_PACK_TYPE = "Pack Type"
SOURCE_SET_TYPE = "Set Type"
FIELD = "tc_shelf_life_days"
MIN_DAYS = 1
MAX_DAYS = 3650


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


# --- Sửa hạn lưu loại gói (FR-M2-07.8, S7) ------------------------------------------------------------------------


def affected_set_types(item: str, new_days: int) -> list[dict]:
	"""Loại bộ lấy `item` làm loại gói mặc định có ghi đè ``0 < override`` mà ``override ≥ new_days``.

	Với hạn loại gói mới, ghi đè đó không còn ngắn hơn nên vô hiệu theo ``min`` (D4). Trả
	``[{"set_type", "override"}]`` theo tên loại bộ.
	"""
	rows = frappe.get_all(
		DOCTYPE,
		filters={"default_pack_type": item, "shelf_life_days": [">=", max(cint(new_days), 1)]},
		fields=["name", "shelf_life_days"],
		order_by="name asc",
	)
	return [{"set_type": row.name, "override": cint(row.shelf_life_days)} for row in rows]


def _pack_type_block(item) -> Block:
	return Block(
		"PACK_TYPE_INVALID",
		_("Shelf life not changed"),
		_("{0} is not a packaging item, so it has no pack type shelf life.").format(item or "-"),
		_("Choose a packaging item."),
	)


def _days_block() -> Block:
	return Block(
		"SHELF_LIFE_INVALID",
		_("Shelf life not changed"),
		_("The shelf life must be a whole number of days from {0} to {1}.").format(MIN_DAYS, MAX_DAYS),
		_("Enter a whole number of days in that range."),
	)


def _reason_block() -> Block:
	return Block(
		"REASON_REQUIRED",
		_("Reason is required"),
		_("A reason of at most {0} characters is required to change a pack type shelf life.").format(
			REASON_MAX
		),
		_("Enter why the shelf life changes."),
	)


def set_pack_shelf_life(item: str, days: int, reason: str) -> dict:
	"""Đổi hạn lưu (ngày) của loại gói `item` kèm lý do (FR-M2-07.8, BRU-REP-009; quyền kiểm ở RPC).

	Từ chối (``BlockedError``, không ghi gì): Item không tồn tại / không phải Packaging → ``PACK_TYPE_INVALID``;
	`days` không phải số nguyên 1-3650 (0 = "chưa có hạn" chỉ có ở dữ liệu mới nhập) → ``SHELF_LIFE_INVALID``; lý do
	trống/chỉ khoảng trắng/quá 500 ký tự → ``REASON_REQUIRED``. Loại gói đã ngừng dùng vẫn sửa được. Khóa dòng Item,
	ghi thẳng ``tc_shelf_life_days`` (không chạy validate của Item) + Audit Log ``Update`` old/new với lý do; cùng giá
	trị cũ thì không ghi gì. Pack đã đóng không đổi (snapshot). Trả
	``{item, old_days, new_days, affected_set_types}`` (cảnh báo, không chặn).
	"""
	item = item.strip() if isinstance(item, str) else ""
	row = (
		frappe.db.get_value(ITEM, item, ["name", "tc_item_group_cssd", FIELD], as_dict=True, for_update=True)
		if item
		else None
	)
	if not row or row.tc_item_group_cssd != PACKAGING:
		raise BlockedError(_pack_type_block(item))
	new_days = whole_number(days)
	if new_days is None or not MIN_DAYS <= new_days <= MAX_DAYS:
		raise BlockedError(_days_block())
	reason = reason.strip() if isinstance(reason, str) else ""
	if not reason or len(reason) > REASON_MAX:
		raise BlockedError(_reason_block())

	old_days = cint(row.get(FIELD))
	if new_days != old_days:
		frappe.db.set_value(ITEM, row.name, FIELD, new_days)
		audit.log("Update", ITEM, row.name, old={FIELD: old_days}, new={FIELD: new_days}, reason=reason)
	return {
		"item": row.name,
		"old_days": old_days,
		"new_days": new_days,
		"affected_set_types": affected_set_types(row.name, new_days),
	}


def audit_item_change(doc, method=None) -> None:
	"""``doc_events["Item"]["on_update"]``: hạn lưu loại gói đổi qua form Item → Audit Log ``Update`` (không chặn).

	Chỉ Item đã có (có bản trước khi lưu) thuộc nhóm Packaging (trước hoặc sau khi lưu) và ``tc_shelf_life_days`` đổi.
	"""
	before = doc.get_doc_before_save()
	if before is None:
		return
	if PACKAGING not in (before.get("tc_item_group_cssd"), doc.get("tc_item_group_cssd")):
		return
	old_days, new_days = cint(before.get(FIELD)), cint(doc.get(FIELD))
	if old_days == new_days:
		return
	audit.log(
		"Update",
		ITEM,
		doc.name,
		old={FIELD: old_days},
		new={FIELD: new_days},
		reason=_("Pack type shelf life changed on the Item form"),
	)
