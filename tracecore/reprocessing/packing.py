"""Đóng gói tại T4 (M2, FEAT-018, UC-08): quy tắc hạn dùng, lô chỉ thị hóa học và đối chiếu BOM.

Phần này chỉ gồm hàm thuần quy tắc, không đổi dữ liệu. Sinh Cycle ID, in lại, hủy và tra cứu (Task 8)
nằm cùng module. M2 không import `tracecore.instrument` (lint R1): dữ liệu của M1/M8 đi qua tham số,
đọc DocType theo tên hoặc hook (`tracecore.core.extension`).
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, formatdate, getdate

from tracecore.core import gs1
from tracecore.core.errors import Block, BlockedError

CI_CLASSES = ("5", "6")  # FR-M2-07.2: lô chỉ thị loại 5/6 theo phương pháp
SOURCE_PACK_TYPE = "Pack Type"
SOURCE_SET_TYPE = "Set Type"


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


# --- Hạn dùng (D4, BRU-REP-009) -----------------------------------------------------------------


def _pack_type_days(item_code):
	"""Hạn lưu (ngày) của loại gói `item_code`; không dùng được làm loại gói → PACK_TYPE_INVALID."""
	row = (
		frappe.db.get_value(
			"Item", item_code, ["tc_item_group_cssd", "tc_shelf_life_days", "disabled"], as_dict=True
		)
		if item_code
		else None
	)
	if not item_code:
		reason = _("No pack type was chosen.")
	elif not row or row.tc_item_group_cssd != "Packaging":
		reason = _("{0} is not a packaging item.").format(item_code)
	elif cint(row.disabled):
		reason = _("Pack type {0} is disabled.").format(item_code)
	elif cint(row.tc_shelf_life_days) <= 0:
		reason = _("Pack type {0} has no shelf life, so the expiry date cannot be calculated.").format(
			item_code
		)
	else:
		return cint(row.tc_shelf_life_days)
	raise _blocked(
		"PACK_TYPE_INVALID",
		_("Pack type cannot be used"),
		reason,
		_("Choose another pack type, or ask R10 to set the shelf life of this one."),
	)


def compute_expiry(packed_on, pack_type, set_type):
	"""Hạn dùng = ngày đóng gói + min(hạn loại gói, hạn ghi đè của loại bộ) (D4).

	Trả ``{"expiry": date, "days": int, "source": "Pack Type" | "Set Type"}``. Loại bộ không ghi đè
	(0/trống) hoặc ghi đè không ngắn hơn hạn loại gói thì nguồn là "Pack Type". Loại gói không phải
	Packaging, đã ngừng dùng hoặc chưa có hạn lưu > 0 thì không dùng được (``PACK_TYPE_INVALID``).
	Số ngày và nguồn trả về là giá trị Task 8 chụp (snapshot) vào Pack.
	"""
	days = _pack_type_days(pack_type)
	source = SOURCE_PACK_TYPE
	override = cint(frappe.db.get_value("Instrument Set Type", set_type, "shelf_life_days"))
	if 0 < override < days:
		days, source = override, SOURCE_SET_TYPE
	return {"expiry": getdate(packed_on) + timedelta(days=days), "days": days, "source": source}


def pack_types(set_type):
	"""Loại gói chọn được cho `set_type`: Item Packaging còn dùng và có hạn lưu > 0.

	Mỗi phần tử là ``{"item", "item_name", "shelf_life_days"}``; loại gói mặc định của loại bộ (nếu còn
	dùng được) đứng đầu, các loại khác theo tên.
	"""
	rows = frappe.get_all(
		"Item",
		filters={"tc_item_group_cssd": "Packaging", "disabled": 0, "tc_shelf_life_days": [">", 0]},
		fields=["name", "item_name", "tc_shelf_life_days"],
		order_by="item_name asc, name asc",
	)
	default = frappe.db.get_value("Instrument Set Type", set_type, "default_pack_type")
	rows.sort(key=lambda row: row.name != default)  # ổn định: mặc định lên đầu, giữ thứ tự tên
	return [
		{"item": row.name, "item_name": row.item_name, "shelf_life_days": cint(row.tc_shelf_life_days)}
		for row in rows
	]


# --- Lô chỉ thị hóa học (BRU-REP-013, BRU-INV-001) ----------------------------------------------


def resolve_ci_batch(raw, method, on_date):
	"""Lô chỉ thị hóa học từ chuỗi quét `raw` cho phương pháp `method`, còn hạn tại ngày `on_date`.

	Làm sạch nhiễu của máy quét (`gs1.clean_scan`), tra Batch không phân biệt hoa/thường và trả tên Batch
	chuẩn: ``{"batch", "item", "expiry_date", "ci_class"}``. Không phải lô chỉ thị loại 5/6 đúng phương pháp,
	không tồn tại, đã ngừng hoặc không có hạn dùng → ``CI_LOT_INVALID``; hết hạn trước `on_date` →
	``CI_LOT_EXPIRED`` (hết hạn đúng ngày `on_date` vẫn dùng được).
	"""
	code = gs1.clean_scan(raw)
	if not code:
		raise _invalid_lot(_("No lot code was scanned."))
	batch = frappe.db.get_value("Batch", code, ["name", "item", "expiry_date", "disabled"], as_dict=True)
	if not batch:
		raise _invalid_lot(_("Lot {0} does not exist.").format(code))
	item = frappe.db.get_value(
		"Item", batch.item, ["tc_item_group_cssd", "tc_compatible_method", "tc_ci_class"], as_dict=True
	)
	if item.tc_item_group_cssd != "Chemical Indicator":
		raise _invalid_lot(_("Lot {0} is not a chemical indicator lot.").format(batch.name))
	if item.tc_ci_class not in CI_CLASSES:
		raise _invalid_lot(
			_("Lot {0} is a class {1} indicator; only class 5 or 6 can be used.").format(
				batch.name, item.tc_ci_class or "-"
			)
		)
	if not item.tc_compatible_method:
		raise _invalid_lot(
			_("The indicator item of lot {0} has no sterilization method set.").format(batch.name)
		)
	if item.tc_compatible_method != method:
		raise _invalid_lot(
			_("Lot {0} is for {1} sterilization, not {2}.").format(
				batch.name, _(item.tc_compatible_method), _(method)
			)
		)
	if cint(batch.disabled):
		raise _invalid_lot(_("Lot {0} has been disabled.").format(batch.name))
	if not batch.expiry_date:
		raise _invalid_lot(_("Lot {0} has no expiry date, so it cannot be checked.").format(batch.name))
	expiry = getdate(batch.expiry_date)
	if expiry < getdate(on_date):
		raise _blocked(
			"CI_LOT_EXPIRED",
			_("Indicator lot has expired"),
			_("Lot {0} expired on {1}.").format(batch.name, formatdate(expiry)),
			_("Scan another indicator lot that is still valid."),
		)
	return {"batch": batch.name, "item": batch.item, "expiry_date": expiry, "ci_class": item.tc_ci_class}


def _invalid_lot(reason):
	return _blocked(
		"CI_LOT_INVALID",
		_("Indicator lot is not valid"),
		reason,
		_("Scan the lot code on a chemical indicator of class 5 or 6 for this sterilization method."),
	)


# --- BOM (BRU-REP-013, FR-M2-07.2) --------------------------------------------------------------


def missing_lines(bom, confirmed):
	"""Các dòng BOM chưa được xác nhận, theo thứ tự BOM.

	`bom` là danh sách dòng từ ``bom.lines`` (mỗi dòng có ``instrument``); `confirmed` là mã dụng cụ đã tick
	(một lần tick phủ cả số lượng của dòng đó).
	"""
	ticked = set(confirmed or ())
	return [line for line in bom if line["instrument"] not in ticked]
