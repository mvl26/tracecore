"""Chi phí và chi phí/kg của lô giặt (FEAT-034; FR-M3-04, .2; FR-M7-03; architecture A-50 D8; #1847 A-104).

M3 không import M7: `linen.laundry.complete` gọi hook `tracecore_after_laundry_complete`, hàm dưới đây (khai báo ở hooks.py)
cộng điện, nước, hóa chất và nhân công theo định mức của chương trình và bảng giá đã duyệt tại ngày hoàn tất, ghi vào lô để
màn trạm hiển thị ngay. Thiếu giá thì bỏ khoản đó và ghi chú; lỗi tính không bao giờ làm hỏng việc hoàn tất lô.

Đơn giá hóa chất (A-104): bảng giá đã duyệt → đơn giá trên dòng định mức của chương trình → giá trị tồn kho bình quân.
"""

import frappe
from frappe import _
from frappe.utils import flt, today

from tracecore.core import program_norm
from tracecore.costing import rates

DOCTYPE = "Laundry Batch"
CURRENCY_DIGITS = 2
SOURCE_LIST, SOURCE_PROGRAM, SOURCE_STOCK = "Price list", "Program", "Stock valuation"
LITRES_PER_M3 = 1000


def on_laundry_complete(ctx):
	"""Tính chi phí lô `ctx["batch"]`; lô thuê ngoài đã có giá/kg riêng nên bỏ qua."""
	if ctx.get("batch_type") == "Outsourced" or not ctx.get("program"):
		return
	try:
		_cost(ctx)
	except Exception:
		frappe.log_error(title=f"FEAT-034 cost {ctx.get('batch')}")


class _Pricer:
	"""Đơn giá tại ngày `day`; gom các khoản thiếu giá vào ``missing`` để ghi chú một lần."""

	def __init__(self, day, norms=()):
		self.day = day
		self.has_version = bool(rates.version_at(day))
		self.missing = [] if self.has_version else [_("an approved cost rate version")]
		self.program_prices = {}
		for norm in norms:
			for line in norm["lines"]:
				if line["unit_price"]:
					self.program_prices.setdefault(line["item"], line["unit_price"])

	def rate(self, rate_type, quantity):
		"""Đơn giá điện, nước, nhân công; không có thì 0 (chỉ ghi thiếu khi thật sự có số lượng)."""
		rate = rates.rate_for(self.day, rate_type) if self.has_version else None
		if rate is None:
			if quantity and self.has_version:
				self._miss(_(rate_type, context="Cost Rate Line"))
			return 0
		return rate

	def item(self, item, quantity=1):
		"""``(đơn giá, nguồn)`` của vật tư theo thứ tự ở đầu file."""
		rate = rates.rate_for(self.day, "Item", item) if self.has_version else None
		if rate is not None:
			return rate, SOURCE_LIST
		if self.program_prices.get(item):
			return self.program_prices[item], SOURCE_PROGRAM
		stock = rates.stock_rate(item)
		if stock:
			return stock, SOURCE_STOCK
		if quantity and self.has_version:
			self._miss(item)
		return 0, None

	def _miss(self, label):
		if label not in self.missing:
			self.missing.append(label)


def norm_breakdown(programs, kg=None, day=None):
	"""Định mức và chi phí định mức của một mẻ chạy `programs` (giặt, có thể thêm sấy) tại ngày `day` (DV-02).

	`kg` bỏ trống thì lấy tải tham chiếu của chương trình đầu. Trả điện, nước, hóa chất, nhân công, tổng, tổng/kg, từng dòng
	hóa chất kèm nguồn đơn giá, giá nước theo đ/m³ và các khoản thiếu giá. Không ghi gì.
	"""
	programs = [program for program in programs if program]
	day = day or today()
	if kg is None and programs:
		kg = program_norm.reference_kg(programs[0])
	kg = flt(kg)
	norms = [program_norm.of(program, kg) for program in programs]
	pricer = _Pricer(day, norms)
	kwh = sum(norm["kwh"] for norm in norms)
	water_l = sum(norm["water_l"] for norm in norms)
	minutes = sum(norm["minutes"] for norm in norms)
	water_rate = pricer.rate("Tap Water", water_l)
	lines = []
	for norm in norms:
		for line in norm["lines"]:
			price, source = pricer.item(line["item"], line["qty"])
			lines.append(
				{**line, "unit_price": price, "price_source": source, "amount": flt(line["qty"] * price)}
			)
	values = {
		"electricity": flt(kwh * pricer.rate("Electricity", kwh)),
		"water": flt(water_l * water_rate),
		"labor": flt(minutes / 60 * pricer.rate("Labor", minutes)),
		"chemical": flt(sum(line["amount"] for line in lines)),
	}
	total = flt(sum(values.values()), CURRENCY_DIGITS)
	return {
		**values,
		"programs": programs,
		"kg": kg,
		"kwh": kwh,
		"water_l": water_l,
		"water_rate_m3": flt(water_rate * LITRES_PER_M3),
		"minutes": minutes,
		"lines": lines,
		"total": total,
		"per_kg": flt(total / kg, CURRENCY_DIGITS) if kg else 0,
		"missing": pricer.missing,
	}


def _quantities(program, kg, chemicals):
	"""Số lượng từng hóa chất/vật tư như `inventory.consume.on_laundry_complete`: người vận hành nhập thay định mức của đúng
	vật tư đó (0 → định mức = mỗi lô + mỗi kg x kg)."""
	norms = frappe.get_all(
		"Program Consumable",
		filters={"parent": program, "parenttype": "Process Program"},
		fields=["item", "qty_per_load", "qty_per_kg"],
		order_by="idx",
	)
	by_item = {norm.item: norm for norm in norms}

	def by_norm(norm):
		return flt(norm.qty_per_load) + flt(norm.qty_per_kg) * kg

	quantities = {}
	for chemical in chemicals or []:
		norm = by_item.get(chemical["item"])
		quantities[chemical["item"]] = flt(chemical.get("qty")) or (by_norm(norm) if norm else 0)
	for norm in norms:
		quantities.setdefault(norm.item, by_norm(norm))
	return quantities


def _cost(ctx):
	day = today()
	values = {field: 0 for field in ("cost_electricity", "cost_water", "cost_chemical", "cost_labor")}
	missing = []
	program = frappe.db.get_value(
		"Process Program",
		ctx["program"],
		["kwh_per_cycle", "water_l_per_cycle", "duration_min"],
		as_dict=True,
	)
	if not rates.version_at(day):
		missing.append(_("an approved cost rate version"))
	else:

		def priced(rate_type, quantity, item=None):
			if not quantity:
				return 0
			rate = rates.rate_for(day, rate_type, item)
			if rate is None:
				missing.append(_(rate_type, context="Cost Rate Line") if not item else item)
				return 0
			return flt(quantity * rate)

		values["cost_electricity"] = priced("Electricity", flt(program.kwh_per_cycle))
		values["cost_water"] = priced("Tap Water", flt(program.water_l_per_cycle))
		values["cost_labor"] = priced("Labor", flt(program.duration_min) / 60)
		kg = flt(ctx.get("kg"))
		values["cost_chemical"] = sum(
			priced("Item", quantity, item)
			for item, quantity in _quantities(ctx["program"], kg, ctx.get("chemicals")).items()
		)
	total = flt(sum(values.values()), CURRENCY_DIGITS)
	kg = flt(ctx.get("kg"))
	values.update(
		cost_total=total,
		cost_per_kg=flt(total / kg, CURRENCY_DIGITS) if kg else 0,
		cost_note=_("No rate for: {0}").format(", ".join(missing)) if missing else None,
	)
	frappe.db.set_value(DOCTYPE, ctx["batch"], values, update_modified=False)
