"""Bảng định giá có phiên bản (FEAT-045, FR-M7-03, FR-M7-04, UC-28, BRU-CST-002; architecture A-48).

R09 lập Nháp, R01 Ghi sổ = duyệt (D2). Định mức theo chương trình ở `Process Program.consumables`, bảng giá chỉ giữ
định mức theo loại gói (D1). M7 không import M5/M6: đọc `Process Program`, `Bin` qua `frappe.get_all` (D6).
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, formatdate, getdate, now_datetime

DOCTYPE = "Cost Rate Version"

# Đơn vị của các đơn giá không phải vật tư (A-48 D4); vật tư dùng stock_uom của Item.
UNIT_BY_TYPE = {"Labor": "hour", "Electricity": "kWh", "Tap Water": "L", "RO Water": "L", "Steam": "kg"}


def _warn(message):
	frappe.msgprint(message, indicator="orange", alert=False)


def validate(doc):
	check_rates(doc)
	check_pack_norms(doc)
	warn_programs_without_norm()


def check_rates(doc):
	seen = set()
	for row in doc.rates:
		if row.rate_type == "Item":
			if not row.item:
				frappe.throw(_("Row {0}: choose the item of this unit price.").format(row.idx))
			row.uom = frappe.db.get_value("Item", row.item, "stock_uom")
		else:
			if row.item:
				frappe.throw(
					_("Row {0}: a {1} price has no item. Clear the item.").format(row.idx, _(row.rate_type))
				)
			row.uom = UNIT_BY_TYPE[row.rate_type]
		key = (row.rate_type, row.item or "")
		if key in seen:
			frappe.throw(
				_("Row {0}: {1} already has a price in this version.").format(
					row.idx, row.item or _(row.rate_type)
				)
			)
		seen.add(key)
		if flt(row.rate) < 0:
			frappe.throw(_("Row {0}: the unit price cannot be negative.").format(row.idx))
		if flt(row.rate) == 0:
			_warn(_("Row {0}: the unit price of {1} is 0.").format(row.idx, row.item or _(row.rate_type)))


def check_pack_norms(doc):
	seen = set()
	for row in doc.pack_norms:
		key = (row.pack_type, row.item)
		if key in seen:
			frappe.throw(
				_("Row {0}: pack type {1} already has a norm for {2}.").format(
					row.idx, row.pack_type, row.item
				)
			)
		seen.add(key)
		if flt(row.qty_per_pack) < 0:
			frappe.throw(_("Row {0}: the quantity per pack cannot be negative.").format(row.idx))
		if flt(row.qty_per_pack) == 0:
			_warn(
				_("Row {0}: the norm of {1} for pack type {2} is 0.").format(row.idx, row.item, row.pack_type)
			)


def warn_programs_without_norm():
	"""FR-M7-04.2: chương trình đang dùng chưa có định mức thì giá thành mẻ của nó không tính được (FEAT-046)."""
	codes = frappe.get_all(
		"Process Program", filters={"is_active": 1, "norm_status": "Missing"}, pluck="program_code"
	)
	if codes:
		_warn(
			_("These active programs have no consumption norm, so their loads cannot be costed: {0}").format(
				", ".join(sorted(codes))
			)
		)


def _approved(**filters):
	"""Các bản đã duyệt (docstatus 1) theo `filters`, khóa dòng để hai lần duyệt cùng lúc không cùng lọt qua."""
	return frappe.db.get_values(
		DOCTYPE,
		{"docstatus": 1, **filters},
		["name", "effective_from", "effective_to"],
		order_by="effective_from desc",
		for_update=True,
		as_dict=True,
	)


def before_submit(doc):
	"""R01 duyệt (UC-28 bước 4): phải có đơn giá, không chồng lấn bản đã duyệt (E1, FR-M7-03.3)."""
	if not doc.rates:
		frappe.throw(_("Add at least one unit price before approving the price list."))
	later = _approved(effective_from=[">=", doc.effective_from], name=["!=", doc.name])
	if later:
		frappe.throw(
			_(
				"Price list {0} is already approved from {1}, so a version starting {2} would overlap it. "
				"Choose a date after {1}."
			).format(later[0].name, formatdate(later[0].effective_from), formatdate(doc.effective_from)),
			title=_("Effective dates overlap"),
		)
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.effective_to = None


def on_submit(doc):
	"""Bản đã duyệt đang mở liền trước kết thúc vào ngày trước hiệu lực của bản mới (A-48 D2)."""
	for previous in _approved(effective_from=["<", doc.effective_from], effective_to=["is", "not set"]):
		frappe.db.set_value(DOCTYPE, previous.name, "effective_to", add_days(doc.effective_from, -1))


def before_cancel(doc):
	"""Chỉ hủy được bản đã duyệt mới nhất; bản cũ hơn đã bị bản sau thay, hủy sẽ để trống một khoảng ngày."""
	later = _approved(effective_from=[">", doc.effective_from])
	if later:
		frappe.throw(
			_("Price list {0} starts later and replaces this one. Cancel {0} first.").format(later[0].name)
		)


def on_cancel(doc):
	"""Bản liền trước (đã bị bản này đóng) mở lại."""
	closed_by_this = add_days(doc.effective_from, -1)
	for previous in _approved(effective_to=closed_by_this):
		frappe.db.set_value(DOCTYPE, previous.name, "effective_to", None)


# --- tra cứu cho tính giá thành (FEAT-046) --------------------------------------------------------------------


def version_at(date):
	"""Bản đã duyệt có hiệu lực tại `date` (FR-M7-03.1); Nháp/Đã hủy không bao giờ dùng (UC-28 E3)."""
	date = getdate(date)
	names = frappe.get_all(
		DOCTYPE,
		filters={"docstatus": 1, "effective_from": ["<=", date]},
		or_filters=[["effective_to", "is", "not set"], ["effective_to", ">=", date]],
		order_by="effective_from desc",
		pluck="name",
		limit=1,
	)
	return names[0] if names else None


def rate_for(date, rate_type, item=None):
	"""Đơn giá `rate_type` (và `item` với vật tư) tại `date`; None khi chưa định giá (FR-M7-05.2)."""
	version = version_at(date)
	if not version:
		return None
	rate = frappe.db.get_value(
		"Cost Rate Line",
		{"parent": version, "parenttype": DOCTYPE, "rate_type": rate_type, "item": item or ("is", "not set")},
		"rate",
	)
	return flt(rate) if rate is not None else None


def pack_norms(date, pack_type):
	"""Định mức theo loại gói `pack_type` tại `date`: ``[{"item", "qty_per_pack"}]`` theo thứ tự dòng."""
	version = version_at(date)
	if not version:
		return []
	return frappe.get_all(
		"Cost Norm Line",
		filters={"parent": version, "parenttype": DOCTYPE, "pack_type": pack_type},
		fields=["item", "qty_per_pack"],
		order_by="idx",
	)


def snapshot(version):
	"""Toàn bộ bảng giá của `version` cho RPC `v1.costing.rate_at`."""
	rows = {"parent": version, "parenttype": DOCTYPE}
	return {
		"rates": frappe.get_all(
			"Cost Rate Line", filters=rows, fields=["rate_type", "item", "uom", "rate"], order_by="idx"
		),
		"pack_norms": frappe.get_all(
			"Cost Norm Line", filters=rows, fields=["pack_type", "item", "qty_per_pack"], order_by="idx"
		),
	}


# --- UC-28 A1: giá bình quân tồn kho -----------------------------------------------------------------------------


def fill_from_stock(doc):
	"""Đơn giá vật tư của bản Nháp = giá bình quân tồn kho hiện tại (tổng giá trị ÷ tổng tồn qua mọi kho, VND không lẻ).

	Vật tư không còn tồn giữ nguyên đơn giá và được trả trong ``skipped``. Không lưu `doc`.
	"""
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft price list can take prices from stock."))
	updated, skipped = [], []
	for row in doc.rates:
		if row.rate_type != "Item" or not row.item:
			continue
		bins = frappe.get_all(
			"Bin",
			filters={"item_code": row.item, "actual_qty": [">", 0]},
			fields=["actual_qty", "stock_value"],
		)
		qty = sum(flt(b.actual_qty) for b in bins)
		if qty <= 0:
			skipped.append(row.item)
			continue
		row.rate = flt(sum(flt(b.stock_value) for b in bins) / qty, 0)
		updated.append(row.item)
	return {"updated": updated, "skipped": skipped}
