"""Xuất kho thủ công vật tư CSSD theo FEFO, bắt buộc lý do (FEAT-042, FR-M6-04, UC-25 E1/E3, BRU-INV-001)."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from tracecore.core.errors import Block, BlockedError
from tracecore.inventory import consume
from tracecore.inventory.receipt import today_vn

SOURCE = "Manual Issue"
FEFO_WARNING = "FEFO_NOT_FOLLOWED"


def _block(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def suggest(item, qty):
	"""Gợi ý lô FEFO cho `qty`: ``{"lots": [{batch, warehouse, qty, expiry_date}], "short"}``."""
	lots, short = consume.pick_lots(item, flt(qty))
	return {
		"lots": [
			{
				"batch": lot.batch,
				"warehouse": lot.warehouse,
				"qty": lot.qty,
				"expiry_date": str(lot.expiry) if lot.expiry else None,
			}
			for lot in lots
		],
		"short": short,
	}


def _title():
	return _("Cannot issue these supplies")


def _check_request(item, qty, reason):
	if not item or not frappe.db.exists("Item", item):
		raise _block(
			"ISSUE_ITEM_INVALID",
			_title(),
			_("Item {0} was not found.").format(item or "-"),
			_("Choose an item from the catalog."),
		)
	if flt(qty) <= 0:
		raise _block(
			"ISSUE_QTY_INVALID",
			_title(),
			_("The quantity must be greater than zero."),
			_("Enter the quantity to issue."),
		)
	if not (reason or "").strip():
		raise _block(
			"REASON_REQUIRED",
			_title(),
			_("A manual issue needs a reason."),
			_("Enter the reason, then issue again."),
		)


def _chosen_lots(item, qty, lots):
	"""Lô người dùng chọn (hoặc gợi ý FEFO nếu không chọn) đã kiểm: thuộc Item, còn hạn, đủ tồn, cộng đúng `qty`."""
	if not lots:
		picked, short = consume.pick_lots(item, qty)
		if short > 0:
			raise _insufficient(item, short)
		return picked
	stock = {(lot.batch, lot.warehouse): lot for lot in consume._stock_by_lot(item)}
	today = today_vn()
	result = []
	for entry in lots:
		batch, amount = entry.get("batch"), flt(entry.get("qty"))
		info = frappe.db.get_value("Batch", batch, ["item", "expiry_date"], as_dict=True) if batch else None
		if not info or info.item != item:
			raise _block(
				"LOT_INVALID",
				_title(),
				_("Lot {0} does not belong to item {1}.").format(batch or "-", item),
				_("Choose a lot of this item."),
			)
		if info.expiry_date and getdate(info.expiry_date) < today:
			raise _block(
				"LOT_EXPIRED",
				_title(),
				_("Lot {0} expired on {1}.").format(batch, frappe.utils.formatdate(info.expiry_date)),
				_("Choose another lot."),
			)
		holders = [lot for key, lot in stock.items() if key[0] == batch]
		holder = max(holders, key=lambda lot: lot.qty, default=None)
		if amount <= 0 or not holder or holder.qty < amount:
			raise _insufficient(item, amount - (holder.qty if holder else 0), batch)
		result.append(consume.Lot(batch, holder.warehouse, amount, info.expiry_date))
	if abs(sum(lot.qty for lot in result) - flt(qty)) > 1e-6:
		raise _block(
			"ISSUE_QTY_INVALID",
			_title(),
			_("The lot quantities add up to {0}, not {1}.").format(sum(lot.qty for lot in result), qty),
			_("Make the lot quantities add up to the quantity to issue."),
		)
	return result


def _insufficient(item, missing, batch=None):
	reason = (
		_("Item {0} is short by {1} in lot {2}.").format(item, missing, batch)
		if batch
		else _("Item {0} is short by {1} in stock.").format(item, missing)
	)
	return _block(
		"STOCK_INSUFFICIENT",
		_title(),
		reason,
		_("Lower the quantity or choose lots with enough stock."),
	)


def _fefo_warnings(item, chosen):
	"""Cảnh báo (FR-M6-04.4) khi dùng lô hạn xa trong lúc còn lô còn hạn, hạn gần hơn và còn tồn."""
	today = today_vn()
	chosen_batches = {lot.batch for lot in chosen}
	latest = max((getdate(lot.expiry) for lot in chosen if lot.expiry), default=None)
	if latest is None:
		return []
	nearer = sorted(
		{
			lot.batch
			for lot in consume._stock_by_lot(item)
			if lot.batch not in chosen_batches and lot.expiry and today <= getdate(lot.expiry) < latest
		}
	)
	if not nearer:
		return []
	return [
		{
			"code": FEFO_WARNING,
			"message": _("Lot {0} expires sooner than the lot you chose and still has stock.").format(
				", ".join(nearer)
			),
		}
	]


def issue(item, qty, reason, lots=None, department=None):
	"""Xuất kho thủ công; trả ``{"entry", "lots", "warnings"}`` hoặc ném ``BlockedError``.

	`lots`: ``[{"batch", "qty"}]`` do người dùng chọn; bỏ trống thì lấy theo FEFO. `department` (xuất cho khoa khác,
	UC-25 A2) được ghi vào lý do. Chưa kiểm quyền: RPC kiểm.
	"""
	_check_request(item, qty, reason)
	chosen = _chosen_lots(item, flt(qty), lots)
	reason = reason.strip()
	if department:
		reason = f"{reason} ({department})"
	rows = [consume.issue_row(item, lot.qty, lot.batch, lot.warehouse) for lot in chosen]
	entry = consume.submit_issue(rows, SOURCE, None, reason)
	return {
		"entry": entry,
		"lots": [{"batch": lot.batch, "qty": lot.qty} for lot in chosen],
		"warnings": _fefo_warnings(item, chosen),
	}
