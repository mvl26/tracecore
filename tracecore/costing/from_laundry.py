"""Chi phí và chi phí/kg của lô giặt khi hoàn tất (FEAT-034; FR-M3-04, .2; FR-M7-03; architecture A-50 D8).

M3 không import M7: `linen.laundry.complete` gọi hook `tracecore_after_laundry_complete`, hàm dưới đây (khai báo ở hooks.py)
cộng điện, nước, hóa chất và nhân công theo định mức của chương trình và bảng giá đã duyệt tại ngày hoàn tất, ghi vào lô để
màn trạm hiển thị ngay. Thiếu giá thì bỏ khoản đó và ghi chú; lỗi tính không bao giờ làm hỏng việc hoàn tất lô.
"""

import frappe
from frappe import _
from frappe.utils import flt, today

from tracecore.costing import rates

DOCTYPE = "Laundry Batch"
CURRENCY_DIGITS = 2


def on_laundry_complete(ctx):
	"""Tính chi phí lô `ctx["batch"]`; lô thuê ngoài đã có giá/kg riêng nên bỏ qua."""
	if ctx.get("batch_type") == "Outsourced" or not ctx.get("program"):
		return
	try:
		_cost(ctx)
	except Exception:
		frappe.log_error(title=f"FEAT-034 cost {ctx.get('batch')}")


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
