"""Vật tư theo chương trình xác nhận tại trạm và trừ kho theo số thực dùng (A-111; FR-M2-03.9, FR-M2-09.9, FR-M5-05.5,
FR-M6-03, FR-M6-03.5, BRU-INV-003).

M2 (T2, T5), M5 (test đầu ngày) và M6 (trừ kho) cùng gọi module này nên không import chéo nhau.

* Định mức của một lô/mẻ/test = ``qty_per_load`` + ``qty_per_pack`` x số bộ/gói + ``qty_per_kg`` x kg, đổi sang ĐVT
  tồn kho (`program_norm.stock_factor`).
* Chương trình có vật tư bắt buộc: Hoàn thành nạp / Bắt đầu test cần nhân viên xác nhận và số > 0 cho mọi vật tư bắt
  buộc (``CONSUMABLES_NOT_CONFIRMED``). Số không sửa = định mức.
* Chỉ thị hóa học, sinh học chỉ để nhắc, không trừ kho theo chương trình (D3): CI trừ theo gói ở T4, BI theo luồng T5.
* A-112: mỗi dòng có lô người vận hành chọn/quét (`core.lots.check`), không chọn thì lô FEFO đầu tiên; kho trừ đúng lô
  của dòng.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from tracecore.core import lots
from tracecore.core.errors import Block, BlockedError
from tracecore.core.program_norm import stock_factor

PRECISION = 6
CHILD = "Run Consumable"
NOT_ISSUED_ROLES = ("Chemical Indicator", "Biological Indicator")


def _program_rows(program):
	if not program:
		return []
	return frappe.get_all(
		"Program Consumable",
		filters={"parent": program, "parenttype": "Process Program"},
		fields=[
			"item",
			"item_name",
			"role",
			"is_required",
			"uom",
			"qty_per_load",
			"qty_per_pack",
			"qty_per_kg",
		],
		order_by="idx asc",
	)


def lines_of(program, units=0, kg=0):
	"""Vật tư của `program` cho một lô/mẻ có `units` bộ/gói (và `kg` kg), theo ĐVT tồn kho."""
	lines = []
	for row in _program_rows(program):
		factor = stock_factor(row.item, row.uom)
		per_load = flt(flt(row.qty_per_load) * factor, PRECISION)
		per_pack = flt(flt(row.qty_per_pack) * factor, PRECISION)
		per_kg = flt(flt(row.qty_per_kg) * factor, PRECISION)
		lines.append(
			{
				"item": row.item,
				"item_name": row.item_name or frappe.db.get_value("Item", row.item, "item_name"),
				"role": row.role or None,
				"is_required": cint(row.is_required),
				"uom": frappe.db.get_value("Item", row.item, "stock_uom"),
				"issued": 0 if row.role in NOT_ISSUED_ROLES else 1,
				"per_load": per_load,
				"per_pack": per_pack,
				"per_kg": per_kg,
				"norm_qty": flt(per_load + per_pack * cint(units) + per_kg * flt(kg), PRECISION),
			}
		)
	return lines


def company_of(program):
	"""Company của máy chạy chương trình theo tài sản của máy (A-78); máy chưa gắn tài sản → None (xét mọi kho)."""
	equipment = program and frappe.db.get_value("Process Program", program, "equipment")
	asset = equipment and frappe.db.get_value("Equipment", equipment, "asset")
	return (asset and frappe.db.get_value("Asset", asset, "company")) or None


def payload(program):
	"""Vật tư gửi kèm danh sách chương trình cho màn trạm: hệ số theo mẻ/gói/kg để màn tự tính định mức, và các lô
	gợi ý theo FEFO ở kho của bệnh viện của máy (``lots``, A-112)."""
	company = company_of(program)
	return [
		{
			**{key: value for key, value in line.items() if key != "norm_qty"},
			"lots": lots.fefo(line["item"], company=company),
		}
		for line in lines_of(program)
	]


def _invalid(reason):
	return BlockedError(
		Block(
			"CONSUMABLE_INVALID",
			_("Consumable quantity is not valid"),
			reason,
			_("Correct the quantities of the consumables, then try again."),
		)
	)


def _given(submitted, lines):
	"""``({vật tư: số thực dùng}, {vật tư: lô})`` từ các dòng gửi lên; mỗi dòng có thể chỉ gửi số, chỉ gửi lô, hoặc cả hai."""
	known = {line["item"] for line in lines}
	given, chosen = {}, {}
	for entry in submitted or []:
		item = entry.get("item") if isinstance(entry, dict) else None
		if item not in known:
			raise _invalid(_("Item {0} is not a consumable of this program.").format(item or "-"))
		batch = entry.get("batch")
		if batch:
			chosen[item] = batch
		if entry.get("qty") in (None, "") and batch:
			continue
		try:
			qty = flt(float(entry.get("qty")), PRECISION)
		except (TypeError, ValueError):
			raise _invalid(_("The quantity of {0} must be a number.").format(item)) from None
		if qty < 0:
			raise _invalid(_("The quantity of {0} cannot be negative.").format(item))
		given[item] = qty
	return given, chosen


def _lot_of(item, batch, company=None):
	"""``(lô, hạn)`` của dòng: lô đã chọn được kiểm (A-112 D2), không chọn thì lô FEFO đầu tiên, không có thì None."""
	if batch:
		checked = lots.check(item, batch, company=company)
		return checked["batch"], checked["expiry_date"]
	first = next(iter(lots.fefo(item, limit=1, company=company)), None)
	return (first["batch"], first["expiry_date"]) if first else (None, None)


def rows(program, units, submitted=None, confirmed=False, operator=None, kg=0, lots_given=None):
	"""Dòng `Run Consumable` của lô/mẻ/test: định mức, thực dùng (không gửi = định mức), người và giờ xác nhận.

	`submitted`: ``[{"item", "qty"?, "batch"?}]`` số thực dùng nhân viên sửa và lô đã chọn/quét. Chương trình có vật tư
	bắt buộc mà chưa xác nhận, hoặc vật tư bắt buộc có số 0 → ``CONSUMABLES_NOT_CONFIRMED``; vật tư lạ, số âm, không phải
	số → ``CONSUMABLE_INVALID``; lô hết hạn, của vật tư khác, đã tắt → ``CONSUMABLE_LOT_INVALID`` (A-112).
	`lots_given` ``{vật tư: lô}``: lô đã chọn ở ô riêng của trạm (hóa chất T2), dùng khi dòng không gửi lô.
	"""
	lines = lines_of(program, units, kg)
	given, chosen = _given(submitted, lines)
	known = {line["item"] for line in lines}
	chosen = {**{item: lot for item, lot in (lots_given or {}).items() if item in known and lot}, **chosen}
	required = [line for line in lines if line["is_required"]]
	actual = {line["item"]: given.get(line["item"], line["norm_qty"]) for line in lines}
	missing = [line["item"] for line in required if actual[line["item"]] <= 0]
	if required and (not cint(confirmed) or missing):
		reason = (
			_("Required consumables have no quantity: {0}.").format(", ".join(missing))
			if cint(confirmed)
			else _("The consumables of program {0} have not been confirmed.").format(program)
		)
		raise BlockedError(
			Block(
				"CONSUMABLES_NOT_CONFIRMED",
				_("Consumables not confirmed"),
				reason,
				_("Check the consumables, enter what was used, tick that they are ready, then try again."),
				object_type="Process Program",
				object_name=program,
			)
		)
	confirmed_at = now_datetime() if cint(confirmed) else None
	company = company_of(program)
	result = []
	for line in lines:
		batch, expiry = _lot_of(line["item"], chosen.get(line["item"]), company)
		result.append(
			{
				"item": line["item"],
				"item_name": line["item_name"],
				"role": line["role"],
				"is_required": line["is_required"],
				"uom": line["uom"],
				"norm_qty": line["norm_qty"],
				"actual_qty": actual[line["item"]],
				"batch": batch,
				"expiry_date": expiry,
				"confirmed_by": operator if cint(confirmed) else None,
				"confirmed_at": confirmed_at,
			}
		)
	return result


def _saved_rows(source_doctype, source_name):
	return frappe.get_all(
		CHILD,
		filters={"parent": source_name, "parenttype": source_doctype},
		fields=["name", "item", "role", "actual_qty", "batch"],
		order_by="idx asc",
	)


def issue_lines(source_doctype, source_name, pinned=None):
	"""Dòng trừ kho ``[{"item", "qty", "batch"}]`` từ vật tư đã xác nhận; None khi nguồn chưa có dòng (dữ liệu cũ).

	Bỏ chỉ thị hóa học, sinh học và dòng số 0. Lô của dòng (A-112) ghim trước; dòng chưa có lô (dữ liệu trước A-112) dùng
	`pinned` ``{vật tư: lô}`` đã chọn ở trạm (hóa chất, gói test), không có thì FEFO.
	"""
	saved = _saved_rows(source_doctype, source_name)
	if not saved:
		return None
	pinned = pinned or {}
	return [
		{"item": row.item, "qty": flt(row.actual_qty, PRECISION), "batch": row.batch or pinned.get(row.item)}
		for row in saved
		if row.role not in NOT_ISSUED_ROLES and flt(row.actual_qty) > 0
	]


def record_lots(source_doctype, source_name, lots):
	"""Ghi các lô đã xuất ``[{"item", "batch", "qty"}]`` vào cột ``lots`` của dòng vật tư (FR-M6-03.5)."""
	by_item = {}
	for lot in lots or []:
		by_item.setdefault(lot["item"], []).append(f"{lot['batch']}: {flt(lot['qty'], PRECISION):g}")
	for row in _saved_rows(source_doctype, source_name):
		if row.item in by_item:
			frappe.db.set_value(CHILD, row.name, "lots", ", ".join(by_item[row.item]), update_modified=False)
