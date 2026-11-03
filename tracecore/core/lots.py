"""Lô vật tư chọn tại trạm: gợi ý FEFO và kiểm lô (A-112; FR-M6-03.6, BRU-INV-004).

M2 (T2, T5), M5 (test đầu ngày) và M6 (trừ kho) cùng gọi module này nên không import chéo nhau.

* `fefo`: lô còn hạn, còn tồn, chưa tắt của một vật tư, hết hạn trước dùng trước; lô không hạn sau cùng.
* `check`: lô người vận hành chọn/quét phải là Batch của đúng vật tư, chưa tắt và còn hạn (``CONSUMABLE_LOT_INVALID``);
  lô hết tồn hoặc sắp hết hạn chỉ được đánh dấu để màn trạm cảnh báo, không chặn (A-112 E2).
"""

from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, flt, formatdate, getdate, nowdate

from tracecore.core.errors import Block, BlockedError

PRECISION = 6
NEAR_EXPIRY_DAYS = 30  # cùng ngưỡng cảnh báo sắp hết hạn của kho (FR-M6-06.1)
NO_EXPIRY = date.max


def today_vn() -> date:
	"""Hôm nay theo múi giờ của System Settings (Asia/Ho_Chi_Minh)."""
	return getdate(nowdate())


def _stock(item):
	"""``{lô: tồn}`` dương của `item` trên mọi kho."""
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	stock = {}
	for row in get_batch_qty(item_code=item, for_stock_levels=True) or []:
		stock[row["batch_no"]] = flt(stock.get(row["batch_no"], 0) + flt(row.get("qty")), PRECISION)
	return {batch: qty for batch, qty in stock.items() if qty > 0}


def fefo(item, limit=5):
	"""Tối đa `limit` lô dùng được của `item`: ``[{"batch", "expiry_date", "qty"}]``, hạn gần trước."""
	if not item:
		return []
	stock = _stock(item)
	if not stock:
		return []
	today = today_vn()
	rows = frappe.get_all(
		"Batch",
		filters={"name": ["in", list(stock)], "item": item, "disabled": 0},
		fields=["name", "expiry_date"],
	)
	usable = [row for row in rows if not row.expiry_date or getdate(row.expiry_date) >= today]
	usable.sort(key=lambda row: (getdate(row.expiry_date) if row.expiry_date else NO_EXPIRY, row.name))
	return [
		{"batch": row.name, "expiry_date": row.expiry_date, "qty": stock[row.name]} for row in usable[:limit]
	]


def _invalid(reason):
	return BlockedError(
		Block(
			"CONSUMABLE_LOT_INVALID",
			_("Consumable lot is not valid"),
			reason,
			_("Scan or choose a lot of this item that has not expired."),
		)
	)


def check(item, batch, on=None):
	"""Kiểm lô `batch` cho `item` tại ngày `on` (mặc định hôm nay giờ VN).

	Trả ``{"batch", "expiry_date", "qty", "no_stock", "near_expiry"}``; lô lạ, của vật tư khác, đã tắt hoặc hết hạn →
	``CONSUMABLE_LOT_INVALID``.
	"""
	row = (
		frappe.db.get_value("Batch", batch, ["name", "item", "expiry_date", "disabled"], as_dict=True)
		if isinstance(batch, str) and batch
		else None
	)
	if not row:
		raise _invalid(_("Lot {0} is not in stock records.").format(batch or "-"))
	if row.item != item:
		raise _invalid(_("Lot {0} belongs to item {1}, not {2}.").format(row.name, row.item, item))
	if row.disabled:
		raise _invalid(_("Lot {0} is disabled.").format(row.name))
	on = getdate(on) if on else today_vn()
	if row.expiry_date and getdate(row.expiry_date) < on:
		raise _invalid(_("Lot {0} expired on {1}.").format(row.name, formatdate(row.expiry_date)))
	qty = _stock(item).get(row.name, 0)
	return {
		"batch": row.name,
		"expiry_date": row.expiry_date,
		"qty": qty,
		"no_stock": qty <= 0,
		"near_expiry": bool(row.expiry_date and getdate(row.expiry_date) <= add_days(on, NEAR_EXPIRY_DAYS)),
	}
