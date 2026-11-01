"""Chi phí và chi phí/kg của lô giặt (FEAT-034; FR-M3-04, .2; FR-M7-03; architecture A-50 D8; #1847 A-104).

M3 không import M7: `linen.laundry.complete` gọi hook `tracecore_after_laundry_complete`, hàm dưới đây (khai báo ở hooks.py)
cộng điện, nước, hóa chất và nhân công theo số thực tế của lô và bảng giá đã duyệt tại ngày hoàn tất, tính cả chi phí định mức
cùng giá đó, ghi vào lô để màn trạm hiển thị ngay. Thiếu giá thì bỏ khoản đó và ghi chú; lỗi tính không bao giờ làm hỏng việc hoàn tất lô.

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


def _quantities(norms, chemicals):
	"""Số lượng từng hóa chất/vật tư như `inventory.consume.on_laundry_complete`: người vận hành nhập thay định mức của đúng
	vật tư đó (0 → định mức); vật tư còn lại của chương trình theo định mức."""
	by_item = {}
	for norm in norms:
		for line in norm["lines"]:
			by_item[line["item"]] = by_item.get(line["item"], 0) + line["qty"]
	quantities = {}
	for chemical in chemicals or []:
		item = chemical["item"]
		quantities[item] = quantities.get(item, 0) + (flt(chemical.get("qty")) or by_item.get(item, 0))
	for item, qty in by_item.items():
		quantities.setdefault(item, qty)
	return quantities


def _chemical_rows(batch, pricer):
	"""Ghi đơn giá, thành tiền lên từng dòng hóa chất của lô; trả tiền hóa chất theo định mức."""
	norm_total = 0
	for row in frappe.get_all(
		"Laundry Batch Chemical",
		filters={"parent": batch, "parenttype": DOCTYPE},
		fields=["name", "item", "qty", "norm_qty"],
	):
		price = pricer.item(row.item, 0)[0]
		norm_total += flt(row.norm_qty) * price
		frappe.db.set_value(
			"Laundry Batch Chemical",
			row.name,
			{"unit_price": price, "amount": flt(flt(row.qty) * price, CURRENCY_DIGITS)},
			update_modified=False,
		)
	return norm_total


def _cost(ctx):
	"""Chi phí theo số thực tế và chi phí định mức cùng bảng giá; nhân công giống nhau ở hai bên (A-104 D9)."""
	kg = flt(ctx.get("kg"))
	batch = frappe.db.get_value(
		DOCTYPE,
		ctx["batch"],
		[
			"dry_program",
			"norm_kwh",
			"norm_dry_kwh",
			"norm_water_l",
			"actual_kwh",
			"actual_dry_kwh",
			"actual_water_l",
		],
		as_dict=True,
	)
	norms = [program_norm.of(program, kg) for program in (ctx["program"], batch.dry_program) if program]
	pricer = _Pricer(today(), norms)
	minutes = sum(norm["minutes"] for norm in norms)
	actual_kwh = flt(batch.actual_kwh) + flt(batch.actual_dry_kwh)
	norm_kwh = flt(batch.norm_kwh) + flt(batch.norm_dry_kwh)
	electricity = pricer.rate("Electricity", actual_kwh or norm_kwh)
	water = pricer.rate("Tap Water", flt(batch.actual_water_l) or flt(batch.norm_water_l))
	labor = flt(minutes / 60 * pricer.rate("Labor", minutes))
	chemical = sum(
		flt(quantity * pricer.item(item, quantity)[0])
		for item, quantity in _quantities(norms, ctx.get("chemicals")).items()
	)
	values = {
		"cost_electricity": flt(actual_kwh * electricity),
		"cost_water": flt(flt(batch.actual_water_l) * water),
		"cost_chemical": flt(chemical),
		"cost_labor": labor,
		"norm_cost_electricity": flt(norm_kwh * electricity),
		"norm_cost_water": flt(flt(batch.norm_water_l) * water),
		"norm_cost_chemical": flt(_chemical_rows(ctx["batch"], pricer), CURRENCY_DIGITS),
	}
	total = flt(
		values["cost_electricity"] + values["cost_water"] + values["cost_chemical"] + labor, CURRENCY_DIGITS
	)
	norm_total = flt(
		values["norm_cost_electricity"] + values["norm_cost_water"] + values["norm_cost_chemical"] + labor,
		CURRENCY_DIGITS,
	)
	values.update(
		cost_total=total,
		cost_per_kg=flt(total / kg, CURRENCY_DIGITS) if kg else 0,
		norm_cost_total=norm_total,
		norm_cost_per_kg=flt(norm_total / kg, CURRENCY_DIGITS) if kg else 0,
		cost_note=_("No rate for: {0}").format(", ".join(pricer.missing)) if pricer.missing else None,
	)
	frappe.db.set_value(DOCTYPE, ctx["batch"], values, update_modified=False)
