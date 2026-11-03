"""Lô vật tư chọn tại trạm: gợi ý FEFO và kiểm lô (A-112; FR-M6-03.6, BRU-INV-004).

M2 (T2, T5), M5 (test đầu ngày) và M6 (trừ kho) cùng gọi module này nên không import chéo nhau.

* `fefo`: lô còn hạn, còn tồn, chưa tắt của một vật tư, hết hạn trước dùng trước; lô không hạn sau cùng.
* `check`: lô người vận hành chọn/quét phải là Batch của đúng vật tư, chưa tắt, còn hạn và không chỉ có ở kho của bệnh
  viện khác (``CONSUMABLE_LOT_INVALID``); lô hết tồn hoặc sắp hết hạn chỉ được đánh dấu để màn trạm cảnh báo, không chặn
  (A-112 D2).
* `lot_code`: mã quét trên hộp vật tư là tên lô, hoặc mã GS1 có AI (10) số lô (A-112 D1).

`company` (A-78): Company của máy chạy lô/mẻ/test; None thì xét kho mọi Company.
"""

import re
from collections import defaultdict
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, flt, formatdate, getdate, nowdate

from tracecore.core import gs1
from tracecore.core.errors import Block, BlockedError

PRECISION = 6
NEAR_EXPIRY_DAYS = 30  # cùng ngưỡng cảnh báo sắp hết hạn của kho (FR-M6-06.1)
NO_EXPIRY = date.max
AI_LOT = "10"
# AI độ dài cố định hay gặp trên hộp vật tư (GTIN, các ngày, SSCC); AI khác dài tới GS hoặc hết chuỗi
FIXED_AI = {"00": 18, "01": 14, "02": 14, "11": 6, "12": 6, "13": 6, "15": 6, "16": 6, "17": 6}
_BRACKETED_AI = re.compile(r"\((\d{2,4})\)([^(]*)")


def today_vn() -> date:
	"""Hôm nay theo múi giờ của System Settings (Asia/Ho_Chi_Minh)."""
	return getdate(nowdate())


def _stock_by_company(item):
	"""``{lô: {Company: tồn}}`` dương của `item` theo Company của kho."""
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	stock = defaultdict(lambda: defaultdict(float))
	companies = {}
	for row in get_batch_qty(item_code=item, for_stock_levels=True) or []:
		warehouse = row.get("warehouse")
		if warehouse not in companies:
			companies[warehouse] = warehouse and frappe.db.get_value("Warehouse", warehouse, "company")
		stock[row["batch_no"]][companies[warehouse]] += flt(row.get("qty"))
	return {
		batch: {company: flt(qty, PRECISION) for company, qty in held.items() if flt(qty, PRECISION) > 0}
		for batch, held in stock.items()
	}


def _stock(item, company=None):
	"""``{lô: tồn}`` dương của `item`; `company` chỉ tính kho của Company đó."""
	stock = {}
	for batch, held in _stock_by_company(item).items():
		qty = flt(held.get(company, 0) if company else sum(held.values()), PRECISION)
		if qty > 0:
			stock[batch] = qty
	return stock


def _gs1_fields(code):
	"""``{AI: giá trị}`` của chuỗi GS1 dạng có ngoặc ``(01)…(10)…`` hoặc dạng liền phân cách bằng GS; sai dạng → {}."""
	if code.startswith("("):
		return {ai: value for ai, value in _BRACKETED_AI.findall(code)}
	fields, rest = {}, code
	while rest:
		ai = rest[:2]
		if not ai.isdigit():
			return {}
		if ai in FIXED_AI:
			size = FIXED_AI[ai]
			value = rest[2 : 2 + size]
			if len(value) != size or not value.isdigit():
				return {}
			fields[ai], rest = value, rest[2 + size :].lstrip(gs1.GS)
			continue
		value, _sep, rest = rest[2:].partition(gs1.GS)
		fields[ai] = value
	return fields


def lot_code(raw):
	"""Mã lô từ chuỗi quét: chuỗi trùng một Batch thì giữ nguyên, ngược lại lấy AI (10) của mã GS1 nếu có."""
	code = gs1.clean_scan(raw) if isinstance(raw, str) else ""
	if not code or frappe.db.exists("Batch", code):
		return code
	return _gs1_fields(code).get(AI_LOT) or code


def fefo(item, limit=5, company=None):
	"""Tối đa `limit` lô dùng được của `item`: ``[{"batch", "expiry_date", "qty"}]``, hạn gần trước."""
	if not item:
		return []
	stock = _stock(item, company)
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


def check(item, batch, on=None, company=None):
	"""Kiểm lô `batch` (tên lô hoặc mã quét) cho `item` tại ngày `on` (mặc định hôm nay giờ VN).

	Trả ``{"batch", "expiry_date", "qty", "no_stock", "near_expiry"}``; lô lạ, của vật tư khác, đã tắt, hết hạn hoặc chỉ
	còn tồn ở kho của Company khác `company` → ``CONSUMABLE_LOT_INVALID``. Lô không còn tồn ở đâu chỉ là ``no_stock``.
	"""
	code = lot_code(batch)
	row = (
		frappe.db.get_value("Batch", code, ["name", "item", "expiry_date", "disabled"], as_dict=True)
		if code
		else None
	)
	if not row:
		raise _invalid(_("Lot {0} is not in stock records.").format(code or "-"))
	if row.item != item:
		raise _invalid(_("Lot {0} belongs to item {1}, not {2}.").format(row.name, row.item, item))
	if row.disabled:
		raise _invalid(_("Lot {0} is disabled.").format(row.name))
	on = getdate(on) if on else today_vn()
	if row.expiry_date and getdate(row.expiry_date) < on:
		raise _invalid(_("Lot {0} expired on {1}.").format(row.name, formatdate(row.expiry_date)))
	held = _stock_by_company(item).get(row.name, {})
	if company and held and company not in held:
		raise _invalid(
			_("Lot {0} is only in stock at {1}, not at {2}.").format(
				row.name, ", ".join(sorted(held)), company
			)
		)
	qty = flt(held.get(company, 0) if company else sum(held.values()), PRECISION)
	return {
		"batch": row.name,
		"expiry_date": row.expiry_date,
		"qty": qty,
		"no_stock": qty <= 0,
		"near_expiry": bool(row.expiry_date and getdate(row.expiry_date) <= add_days(on, NEAR_EXPIRY_DAYS)),
	}
