"""Bảng định giá có phiên bản (FEAT-045, FR-M7-03, FR-M7-04, UC-28, BRU-CST-002; architecture A-48).

R09 lập Nháp, R01 Ghi sổ = duyệt (D2). Định mức theo chương trình ở `Process Program.consumables`, bảng giá chỉ giữ
định mức theo loại gói (D1). M7 không import M5/M6: đọc `Process Program`, `Bin` qua `frappe.get_all` (D6).
"""

import frappe
from frappe import _
from frappe.utils import flt

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


def before_submit(doc):
	pass


def on_submit(doc):
	pass


def before_cancel(doc):
	pass


def on_cancel(doc):
	pass
