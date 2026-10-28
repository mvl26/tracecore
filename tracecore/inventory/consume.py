"""Tiêu hao vật tư tự động theo lô rửa / mẻ tiệt khuẩn và chọn lô FEFO (FEAT-042, FR-M6-03, BRU-INV-001/002).

M2 gọi hook ``tracecore_after_wash_complete`` / ``tracecore_after_load_release``; hàm ``on_*`` ở đây là người nghe
(M2 không import M6). Mỗi nguồn (lô rửa, mẻ) chỉ có một Stock Entry ``Material Issue`` còn hiệu lực
(``tc_source_doctype`` + ``tc_source_name``), nên hook chạy lại không trừ kho hai lần.

Tồn không đủ (FR-M6-03.2): trừ phần đang có, ghi phần thiếu vào lý do của phiếu và báo R09 xuất bù khi nhập hàng
(ERPNext chặn tồn âm theo lô nên không trừ vượt). Lỗi bất ngờ không được làm hỏng mẻ.
"""

from collections import defaultdict
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt, getdate

from tracecore.core import notification
from tracecore.inventory.receipt import today_vn

ISSUE = "Material Issue"
SAVEPOINT = "tc_consume"
NO_EXPIRY = getdate("9999-12-31")
PRECISION = 6


@dataclass(frozen=True)
class Lot:
	batch: str
	warehouse: str
	qty: float
	expiry: object = None


def _stock_by_lot(item):
	"""Lô còn tồn dương của `item` theo kho: ``[Lot]`` chưa sắp thứ tự."""
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	rows = get_batch_qty(item_code=item, for_stock_levels=True) or []
	expiry = {
		row.name: row.expiry_date
		for row in frappe.get_all(
			"Batch",
			filters={"name": ["in", [r.get("batch_no") for r in rows] or [""]]},
			fields=["name", "expiry_date"],
		)
	}
	return [
		Lot(row["batch_no"], row.get("warehouse"), flt(row["qty"], PRECISION), expiry.get(row["batch_no"]))
		for row in rows
		if flt(row.get("qty"), PRECISION) > 0
	]


def pick_lots(item, qty, batch=None, taken=None):
	"""Chọn lô theo FEFO cho `qty` của `item`: ``([Lot(qty lấy)], phần thiếu)``.

	Chỉ lấy lô còn hạn (hạn ≥ hôm nay giờ VN), hạn gần trước, lô không hạn sau cùng. `batch` ghim một lô cụ thể
	(người vận hành đã quét lô hóa chất). `taken` (``{(lô, kho): đã lấy}``) cộng dồn qua nhiều dòng của cùng một phiếu.
	"""
	taken = taken if taken is not None else defaultdict(float)
	today = today_vn()
	candidates = [
		lot
		for lot in _stock_by_lot(item)
		if (batch is None or lot.batch == batch) and (lot.expiry is None or getdate(lot.expiry) >= today)
	]
	candidates.sort(key=lambda lot: (getdate(lot.expiry) if lot.expiry else NO_EXPIRY, lot.batch))
	need = flt(qty, PRECISION)
	picked = []
	for lot in candidates:
		if need <= 0:
			break
		free = flt(lot.qty - taken[(lot.batch, lot.warehouse)], PRECISION)
		take = min(free, need)
		if take <= 0:
			continue
		taken[(lot.batch, lot.warehouse)] += take
		picked.append(Lot(lot.batch, lot.warehouse, take, lot.expiry))
		need = flt(need - take, PRECISION)
	return picked, max(need, 0)


def _existing_entry(source_doctype, source_name):
	names = frappe.get_all(
		"Stock Entry",
		filters={"tc_source_doctype": source_doctype, "tc_source_name": source_name, "docstatus": ["<", 2]},
		pluck="name",
		limit=1,
	)
	return names[0] if names else None


def issue_row(item, qty, batch, warehouse):
	uom = frappe.db.get_value("Item", item, "stock_uom")
	return {
		"item_code": item,
		"qty": qty,
		"uom": uom,
		"stock_uom": uom,
		"conversion_factor": 1,
		"s_warehouse": warehouse,
		"use_serial_batch_fields": 1,
		"batch_no": batch,
	}


def consume_for(source_doctype, source_name, lines, reason):
	"""Một Stock Entry ``Material Issue`` đã ghi sổ cho nguồn ``(source_doctype, source_name)``.

	`lines`: ``[{"item", "qty", "batch"?}]`; dòng qty ≤ 0 bị bỏ. Trả ``{"entry", "created", "lots", "short"}``;
	``entry`` là None khi không có dòng nào. Nguồn đã có phiếu còn hiệu lực thì trả phiếu đó, không tạo thêm.
	"""
	existing = _existing_entry(source_doctype, source_name)
	if existing:
		return {"entry": existing, "created": False, "lots": [], "short": []}
	taken = defaultdict(float)
	rows, lots, short = [], [], []
	for line in lines:
		qty = flt(line.get("qty"), PRECISION)
		if qty <= 0:
			continue
		item, batch = line["item"], line.get("batch")
		picked, missing = pick_lots(item, qty, batch, taken)
		rows += [issue_row(item, lot.qty, lot.batch, lot.warehouse) for lot in picked]
		lots += [{"item": item, "batch": lot.batch, "qty": lot.qty} for lot in picked]
		if missing > 0:
			short.append({"item": item, "qty": missing})
	if not rows:
		return {"entry": None, "created": False, "lots": [], "short": short}
	if short:
		reason = "{}. {}".format(
			reason,
			_("Short, not issued: {0}").format(", ".join(f"{row['item']}: {row['qty']}" for row in short)),
		)
	entry = submit_issue(rows, source_doctype, source_name, reason)
	return {"entry": entry, "created": True, "lots": lots, "short": short}


def submit_issue(rows, source_doctype, source_name, reason):
	"""Lập và ghi sổ Stock Entry ``Material Issue`` từ các dòng ``issue_row``; trả tên phiếu."""
	import erpnext

	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": ISSUE,
			"purpose": ISSUE,
			"company": erpnext.get_default_company(),
			"posting_date": today_vn(),
			"tc_source_doctype": source_doctype,
			"tc_source_name": source_name,
			"tc_reason": reason,
			"items": rows,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	return doc.name


# --- người nghe hook của M2 --------------------------------------------------------------------------------------


def _norms(program):
	if not program:
		return []
	return frappe.get_all(
		"Program Consumable",
		filters={"parent": program, "parenttype": "Process Program"},
		fields=["item", "qty_per_load", "qty_per_pack"],
		order_by="idx",
	)


def _norm_qty(norm, units):
	return flt(norm.qty_per_load) + flt(norm.qty_per_pack) * units


def _notify(event, source_doctype, source_name, subject):
	"""Báo R09; lỗi gửi thông báo không được làm hỏng mẻ đang giải phóng."""
	try:
		notification.emit(event, frappe._dict(doctype=source_doctype, name=source_name), subject)
	except Exception:
		frappe.log_error(title=f"FEAT-042 notify {event} {source_doctype} {source_name}")


def _run(source_doctype, source_name, lines, reason):
	"""Trừ kho, không bao giờ làm hỏng bước gọi: lỗi được ghi Error Log và báo R09."""
	if not lines:
		_notify(
			"CONSUMPTION_NO_NORM",
			source_doctype,
			source_name,
			_("{0} {1} has no consumption norm, so nothing was deducted from stock").format(
				source_doctype, source_name
			),
		)
		return None
	frappe.db.savepoint(SAVEPOINT)
	try:
		result = consume_for(source_doctype, source_name, lines, reason)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title=f"FEAT-042 consume {source_doctype} {source_name}")
		_notify(
			"CONSUMPTION_FAILED",
			source_doctype,
			source_name,
			_("Automatic consumption for {0} {1} failed. Issue the supplies by hand.").format(
				source_doctype, source_name
			),
		)
		return None
	if result["short"]:
		_notify(
			"CONSUMPTION_SHORT",
			source_doctype,
			source_name,
			_("{0} {1} needed more than the stock on hand ({2}). The shortage was not issued.").format(
				source_doctype,
				source_name,
				", ".join(f"{row['item']}: {row['qty']}" for row in result["short"]),
			),
		)
	return result


def on_wash_complete(ctx):
	"""Lô rửa Đạt: hóa chất theo lô và số lượng đã ghi (0 → định mức), cộng các vật tư khác của chương trình."""
	if ctx.get("result") != "Pass":
		return
	norms = _norms(ctx.get("program"))
	units = len(ctx.get("sets") or [])
	by_item = {norm.item: norm for norm in norms}
	lines = []
	covered = set()
	for chemical in ctx.get("chemicals") or []:
		norm = by_item.get(chemical["item"])
		qty = flt(chemical.get("qty")) or (_norm_qty(norm, units) if norm else 0)
		lines.append({"item": chemical["item"], "qty": qty, "batch": chemical.get("lot")})
		covered.add(chemical["item"])
	lines += [
		{"item": norm.item, "qty": _norm_qty(norm, units)} for norm in norms if norm.item not in covered
	]
	_run("Wash Batch", ctx["batch"], lines, _("Automatic consumption of wash batch {0}").format(ctx["batch"]))


def on_load_release(ctx):
	"""Mẻ tiệt khuẩn giải phóng: định mức chương trình x số gói, lô theo FEFO."""
	packs = len(ctx.get("packs") or [])
	lines = [{"item": norm.item, "qty": _norm_qty(norm, packs)} for norm in _norms(ctx.get("program"))]
	_run(
		"Sterilization Load",
		ctx["load"],
		lines,
		_("Automatic consumption of sterilization load {0}").format(ctx["load"]),
	)
