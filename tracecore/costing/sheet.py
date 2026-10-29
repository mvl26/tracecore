"""Cost Sheet mẻ tiệt khuẩn / lô rửa và giá thành gói (FEAT-046; FR-M7-05, .1, .2, FR-M7-06, .2; UC-29; A-53).

M7 không import M1-M6/M8: đọc `Sterilization Load`, `Wash Batch`, `Pack`, `Set Unit`, `Equipment`, `Process Program`,
`Stock Entry`, `Set BOM Item`, `Instrument` theo tên DocType và nhận sự kiện qua hook (hàm ``on_*`` ở cuối file).

Chi phí mẻ/lô = khấu hao máy/mẻ + điện + nước + hơi + hóa chất/chỉ thị + nhân công + bảo trì phân bổ, theo đơn giá của
phiên bản giá hiệu lực tại ngày nghiệp vụ (chụp vào Cost Sheet, không tính lại khi bảng giá đổi). Mẻ đạt chia theo số
gói; mỗi gói cộng phần lô rửa của bộ, lắp ráp, bao gói và khấu hao dụng cụ (bộ mượn không khấu hao) thành giá thành gói
cho chu trình (`Pack.cost_total`). Thiếu giá một khoản → khoản đó 0 đ, Cost Sheet "Chưa định giá" và báo R09.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

from tracecore.core.notification import emit
from tracecore.costing import entry, rates

DOCTYPE = "Cost Sheet"
LOAD, WASH = "Sterilization Load", "Wash Batch"
SOURCES = (LOAD, WASH)
RATE_DOCTYPE = rates.DOCTYPE
UNPRICED_EVENT = "COST_SHEET_UNPRICED"
COMPONENTS = (
	"Equipment Depreciation",
	"Electricity",
	"Tap Water",
	"Steam",
	"Chemical",
	"Labor",
	"Maintenance",
)
# khoản theo định mức chương trình: (thành phần, loại giá, trường định mức, hệ số đổi ra đơn vị giá)
PROGRAM_NORMS = (
	("Electricity", "Electricity", "kwh_per_cycle", 1),
	("Tap Water", "Tap Water", "water_l_per_cycle", 1),
	("Steam", "Steam", "steam_kg_per_cycle", 1),
	("Labor", "Labor", "duration_min", 1 / 60),
)


def vnd(value) -> int:
	"""Làm tròn VND không lẻ (nửa lên)."""
	return int(Decimal(str(flt(value))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def split(total: int, count: int) -> list[int]:
	"""Chia đều `total` cho `count` phần nguyên; phần cuối nhận phần dư để tổng khớp đúng tới đồng."""
	if count <= 0:
		return []
	part = total // count
	return [part] * (count - 1) + [total - part * (count - 1)]


# --- đơn giá theo một phiên bản ------------------------------------------------------------------------------------


class Pricer:
	"""Đơn giá của một phiên bản đã duyệt; ghi lại khoản thiếu giá (FR-M7-05.2)."""

	def __init__(self, version):
		self.version = version
		self.missing = []
		self._cache = {}

	def rate(self, rate_type, item=None):
		key = (rate_type, item)
		if key not in self._cache:
			value = None
			if self.version:
				value = frappe.db.get_value(
					"Cost Rate Line",
					{
						"parent": self.version,
						"parenttype": RATE_DOCTYPE,
						"rate_type": rate_type,
						"item": item or ("is", "not set"),
					},
					"rate",
				)
			self._cache[key] = flt(value) if value is not None else None
		return self._cache[key]

	def price(self, rate_type, quantity, item=None, label=None):
		"""(đơn giá, thành tiền VND); số lượng > 0 mà thiếu giá → ghi thiếu, thành tiền 0."""
		if not flt(quantity):
			return 0, 0
		rate = self.rate(rate_type, item)
		if rate is None:
			name = item or label or _(rate_type, context="Cost Rate Line")
			if name not in self.missing:
				self.missing.append(name)
			return 0, 0
		return rate, vnd(flt(quantity) * rate)

	def pack_norms(self, pack_type):
		if not (self.version and pack_type):
			return []
		return frappe.get_all(
			"Cost Norm Line",
			filters={"parent": self.version, "parenttype": RATE_DOCTYPE, "pack_type": pack_type},
			fields=["item", "qty_per_pack"],
			order_by="idx",
		)


# --- dữ liệu nguồn -----------------------------------------------------------------------------------------------


def _source(source_doctype, source_name):
	if source_doctype == LOAD:
		row = frappe.db.get_value(
			LOAD,
			source_name,
			["equipment", "program", "status", "started_at", "ended_at", "released_at"],
			as_dict=True,
		)
		packs = frappe.get_all(
			"Load Pack",
			filters={"parent": source_name, "parenttype": LOAD},
			fields=["pack", "set_unit"],
			order_by="idx",
		)
		moment = row.released_at or row.ended_at or row.started_at
		return frappe._dict(
			row, packs=packs, sets=[p.set_unit for p in packs], failed=row.status == "Failed", moment=moment
		)
	row = frappe.db.get_value(
		WASH, source_name, ["equipment", "program", "status", "started_at", "ended_at"], as_dict=True
	)
	sets = frappe.get_all(
		"Wash Batch Set Unit",
		filters={"parent": source_name, "parenttype": WASH},
		pluck="set_unit",
		order_by="idx",
	)
	return frappe._dict(row, packs=[], sets=sets, failed=False, moment=row.ended_at or row.started_at)


def _consumed(source_doctype, source_name):
	"""{item: số lượng} đã xuất kho tự động cho nguồn (Stock Entry ghi sổ của FEAT-042); rỗng khi chưa có."""
	entries = frappe.get_all(
		"Stock Entry",
		filters={"docstatus": 1, "tc_source_doctype": source_doctype, "tc_source_name": source_name},
		pluck="name",
	)
	quantities = {}
	if entries:
		for row in frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": ["in", entries], "parenttype": "Stock Entry"},
			fields=["item_code", "transfer_qty", "qty"],
		):
			quantities[row.item_code] = quantities.get(row.item_code, 0) + flt(row.transfer_qty or row.qty)
	return quantities


def _norm_consumption(program, pack_count):
	"""Hóa chất/chỉ thị theo định mức chương trình khi chưa có phiếu xuất: mỗi mẻ + mỗi gói nhân số gói."""
	quantities = {}
	for row in frappe.get_all(
		"Program Consumable",
		filters={"parent": program, "parenttype": "Process Program"},
		fields=["item", "qty_per_load", "qty_per_pack"],
		order_by="idx",
	):
		quantities[row.item] = (
			quantities.get(row.item, 0) + flt(row.qty_per_load) + flt(row.qty_per_pack) * pack_count
		)
	return quantities


def _maintenance_today(equipment, day):
	"""Tổng chi phí của các Cost Entry đã ghi sổ phân bổ cho máy, phần rơi vào ngày `day`."""
	parents = frappe.get_all(
		"Cost Allocation",
		filters={"parenttype": "Cost Entry", "target_type": "Equipment", "target": equipment},
		pluck="parent",
	)
	if not parents:
		return 0
	total = 0
	for name in frappe.get_all(
		"Cost Entry",
		filters={
			"name": ["in", parents],
			"docstatus": 1,
			"period_from": ["<=", day],
			"period_to": [">=", day],
		},
		pluck="name",
	):
		total += entry.allocated_to(frappe.get_doc("Cost Entry", name), "Equipment", equipment, day, day)
	return total


def _loads_on_day(equipment, day):
	"""Số mẻ/lô của máy bắt đầu trong ngày (tối thiểu 1): mẫu số chia chi phí bảo trì theo ngày."""
	start, end = f"{day} 00:00:00", f"{day} 23:59:59"
	count = sum(
		frappe.db.count(
			doctype, {"equipment": equipment, "docstatus": ["<", 2], "started_at": ["between", [start, end]]}
		)
		for doctype in SOURCES
	)
	return max(count, 1)


def _set_value(set_type, bom_version):
	"""Giá trị bộ = Σ giá trị dụng cụ nhân số lượng của BOM phiên bản (FR-M7-06)."""
	filters = {"set_type": set_type}
	if bom_version:
		filters["bom_version"] = bom_version
	total = 0
	for row in frappe.get_all("Set BOM Item", filters=filters, fields=["instrument", "qty"]):
		total += flt(frappe.db.get_value("Instrument", row.instrument, "value")) * flt(row.qty)
	return total


def _wash_share(set_unit, before):
	"""Phần chi phí lô rửa của bộ: Cost Sheet của lô rửa gần nhất có bộ, bắt đầu trước `before`, chia đều số bộ."""
	batches = frappe.get_all(
		"Wash Batch Set Unit", filters={"set_unit": set_unit, "parenttype": WASH}, pluck="parent"
	)
	if not batches:
		return 0
	latest = frappe.get_all(
		WASH,
		filters={"name": ["in", batches], "started_at": ["<=", get_datetime(before)]},
		pluck="name",
		order_by="started_at desc",
		limit=1,
	)
	if not latest:
		return 0
	total = frappe.db.get_value(
		DOCTYPE, {"source_doctype": WASH, "source_name": latest[0], "is_recalculation": 0}, "total_cost"
	)
	if not total:
		return 0
	count = frappe.db.count("Wash Batch Set Unit", {"parent": latest[0], "parenttype": WASH})
	return vnd(total) // max(count, 1)


# --- lập Cost Sheet -----------------------------------------------------------------------------------------------


def _lines(source_doctype, source_name, src, pricer):
	lines = []
	depreciation = (
		vnd(frappe.db.get_value("Equipment", src.equipment, "depreciation_per_load")) if src.equipment else 0
	)
	lines.append(
		{
			"component": "Equipment Depreciation",
			"quantity": 1,
			"rate": depreciation,
			"amount": depreciation,
			"priced": 1,
		}
	)
	program = (
		frappe.db.get_value(
			"Process Program",
			src.program,
			["kwh_per_cycle", "water_l_per_cycle", "steam_kg_per_cycle", "duration_min"],
			as_dict=True,
		)
		if src.program
		else frappe._dict()
	)
	for component, rate_type, field, factor in PROGRAM_NORMS:
		quantity = flt(program.get(field)) * factor
		rate, amount = pricer.price(rate_type, quantity)
		if quantity:
			lines.append(
				{
					"component": component,
					"quantity": quantity,
					"uom": rates.UNIT_BY_TYPE.get(rate_type),
					"rate": rate,
					"amount": amount,
					"priced": int(bool(rate)),
				}
			)
	consumed = _consumed(source_doctype, source_name) or (
		_norm_consumption(src.program, len(src.packs)) if src.program else {}
	)
	for item, quantity in consumed.items():
		rate, amount = pricer.price("Item", quantity, item)
		lines.append(
			{
				"component": "Chemical",
				"item": item,
				"quantity": quantity,
				"rate": rate,
				"amount": amount,
				"priced": int(bool(rate)),
			}
		)
	if src.equipment and src.moment:
		day = getdate(src.moment)
		maintenance = _maintenance_today(src.equipment, day)
		if maintenance:
			share = vnd(flt(maintenance) / _loads_on_day(src.equipment, day))
			lines.append(
				{"component": "Maintenance", "quantity": 1, "rate": share, "amount": share, "priced": 1}
			)
	return lines


def _pack_rows(src, shares, pricer):
	rows = []
	for pack, share in zip(src.packs, shares, strict=True):
		info = frappe.db.get_value(
			"Pack",
			pack.pack,
			["set_unit", "set_type", "department", "method", "pack_type", "bom_version"],
			as_dict=True,
		)
		unit = (
			frappe.db.get_value("Set Unit", info.set_unit, ["is_loaner", "max_cycles"], as_dict=True)
			or frappe._dict()
		)
		minutes = (
			flt(frappe.db.get_value("Instrument Set Type", info.set_type, "assembly_minutes"))
			if info.set_type
			else 0
		)
		_rate, assembly = pricer.price("Labor", minutes / 60, label=_("Labor", context="Cost Rate Line"))
		packaging = sum(
			pricer.price("Item", flt(norm.qty_per_pack), norm.item)[1]
			for norm in pricer.pack_norms(info.pack_type)
		)
		depreciation = 0
		if not cint(unit.get("is_loaner")) and cint(unit.get("max_cycles")):
			depreciation = vnd(_set_value(info.set_type, info.bom_version) / cint(unit.max_cycles))
		wash = vnd(_wash_share(info.set_unit, src.started_at or src.moment or now_datetime()))
		rows.append(
			{
				"pack": pack.pack,
				"set_unit": info.set_unit,
				"set_type": info.set_type,
				"department": info.department,
				"method": info.method,
				"load_share": share,
				"wash_share": wash,
				"assembly_cost": assembly,
				"packaging_cost": packaging,
				"instrument_depreciation": depreciation,
				"total": share + wash + assembly + packaging + depreciation,
			}
		)
	return rows


def current(source_doctype, source_name):
	"""Tên Cost Sheet chính (không phải bản tính lại) của nguồn, hoặc None."""
	return frappe.db.get_value(
		DOCTYPE, {"source_doctype": source_doctype, "source_name": source_name, "is_recalculation": 0}, "name"
	)


def build(source_doctype, source_name, rate_version=None, note=None, recalculation=False) -> str:
	"""Lập Cost Sheet cho mẻ/lô; trả tên. Bản chính idempotent theo nguồn; `recalculation` tạo bản tính lại mới."""
	if source_doctype not in SOURCES:
		frappe.throw(_("Cost sheets are built for sterilization loads and wash batches only."))
	existing = current(source_doctype, source_name)
	if existing and not recalculation:
		return existing
	src = _source(source_doctype, source_name)
	day = getdate(src.moment or now_datetime())
	version = rate_version or rates.version_at(day)
	pricer = Pricer(version)
	if not version:
		pricer.missing.append(_("an approved cost rate version"))
	lines = _lines(source_doctype, source_name, src, pricer)
	total = sum(cint(line["amount"]) for line in lines)
	packs = []
	if source_doctype == LOAD and not src.failed and src.packs:
		packs = _pack_rows(src, split(total, len(src.packs)), pricer)
	count = len(src.packs) if source_doctype == LOAD else len(src.sets)
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"status": "Unpriced" if pricer.missing else "Priced",
			"is_quality_cost": int(src.failed),
			"is_recalculation": int(bool(recalculation)),
			"supersedes": existing if recalculation else None,
			"recalc_note": note,
			"cost_date": day,
			"equipment": src.equipment,
			"program": src.program,
			"rate_version": version,
			"pack_count": count,
			"total_cost": total,
			"cost_per_pack": total // count if count else 0,
			"missing_rates": ", ".join(pricer.missing) or None,
			"lines": lines,
			"packs": packs,
		}
	)
	doc.flags.tc_cost_sheet = True
	doc.insert(ignore_permissions=True)
	if not recalculation:
		for row in packs:
			frappe.db.set_value("Pack", row["pack"], "cost_total", row["total"], update_modified=False)
		if source_doctype == WASH:
			frappe.db.set_value(WASH, source_name, "cost_total", total, update_modified=False)
		if pricer.missing:
			emit(
				UNPRICED_EVENT,
				doc,
				_("Cost sheet {0} is unpriced").format(doc.name),
				_("No rate for: {0}").format(", ".join(pricer.missing)),
			)
	return doc.name
