"""Nhắc và kiểm tra bảo dưỡng dụng cụ tại T4 (M1, FEAT-018, FR-M1-09, BRU-REP-014).

M2 (đóng gói) không import module này (lint R1): các hàm được khai báo trong ``hooks.py`` và M2 gọi qua
``tracecore.core.extension.run`` — ``pack_context`` (``tracecore_pack_context``), ``check_pack``
(``tracecore_pack_checks``) và ``apply_pack`` (``tracecore_after_cycle_id``).

Quy tắc ngưỡng (D5), so sánh bằng số nguyên để không lệch do số thực:

- không nhắc khi dụng cụ không khai báo ngưỡng, hoặc ``cycles_since < interval``
  (chưa có dòng Instrument Maintenance = 0 chu trình);
- ``due``: ``cycles_since >= interval``;
- ``overdue``: ``due`` và (``cycles_since * 10 > interval * 12``, tức vượt ngưỡng quá 20 %,
  hoặc ``deferred_count >= 3``). Dụng cụ ``overdue`` không còn được hoãn (``can_defer`` False).
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core import gs1
from tracecore.core.errors import Block, BlockedError
from tracecore.instrument import bom

STATE_DUE = "due"
STATE_OVERDUE = "overdue"
ACTION_DONE = "Done"
ACTION_DEFERRED = "Deferred"
ACTIONS = (ACTION_DONE, ACTION_DEFERRED)
MAX_DEFERRALS = 3  # hoãn đủ 3 lần thì chặn hoãn tiếp (FR-M1-09.6)
LUBRICATION = "Lubrication"  # Instrument.maint_type phải kèm lô dầu khi xác nhận Đã bảo dưỡng
LUBRICANT_GROUP = "Lubricant"  # Item.tc_item_group_cssd của lô dầu


def _state(interval, cycles_since, deferred_count):
	"""``None`` (chưa đến hạn), ``"due"`` hoặc ``"overdue"``."""
	if interval <= 0 or cycles_since < interval:
		return None
	if cycles_since * 10 > interval * 12 or deferred_count >= MAX_DEFERRALS:
		return STATE_OVERDUE
	return STATE_DUE


def _reminders_from_db(ctx):
	"""Nhắc bảo dưỡng của bộ trong ``ctx`` theo BOM hiện hành, theo thứ tự BOM (mỗi dụng cụ một lần)."""
	set_unit = ctx["set_unit"]["name"]
	set_type = ctx["set_type"]
	lines = bom.lines(set_type["name"], cint(set_type.get("current_bom_version")))
	if not lines:
		return []
	codes = list({line["instrument"] for line in lines})
	instruments = {
		row.name: row
		for row in frappe.get_all(
			"Instrument",
			filters={"name": ["in", codes], "maint_interval_cycles": [">", 0]},
			fields=["name", "maint_interval_cycles", "maint_type"],
		)
	}
	counters = {
		row.instrument: row
		for row in frappe.get_all(
			"Instrument Maintenance",
			filters={"set_unit": set_unit, "instrument": ["in", codes]},
			fields=["instrument", "cycles_since_maint", "deferred_count"],
		)
	}
	items, seen = [], set()
	for line in lines:
		code = line["instrument"]
		if code in seen or code not in instruments:
			continue
		seen.add(code)
		interval = cint(instruments[code].maint_interval_cycles)
		counter = counters.get(code)
		cycles_since = cint(counter.cycles_since_maint) if counter else 0
		deferred_count = cint(counter.deferred_count) if counter else 0
		state = _state(interval, cycles_since, deferred_count)
		if state is None:
			continue
		items.append(
			{
				"instrument": code,
				"instrument_name": line["instrument_name"],
				"image": line["image"],
				"maint_type": instruments[code].maint_type or None,
				"interval": interval,
				"cycles_since": cycles_since,
				"deferred_count": deferred_count,
				"state": state,
				"can_defer": state == STATE_DUE,
			}
		)
	return items


def _reminders(ctx):
	"""Nhắc mà người dùng đã thấy (``ctx["maintenance"]`` do ``pack_context`` gộp vào); chưa có thì tính lại."""
	snapshot = ctx.get("maintenance")
	return snapshot if snapshot is not None else _reminders_from_db(ctx)


def _actions(ctx):
	"""``{dụng cụ: action}`` từ ``ctx["maint_actions"]``; action không phải Done/Deferred coi như chưa có."""
	actions = {}
	for action in ctx.get("maint_actions") or []:
		if action.get("instrument") and action.get("action") in ACTIONS:
			actions[action["instrument"]] = action
	return actions


def pack_context(ctx):
	"""Hook ``tracecore_pack_context``: các nhắc bảo dưỡng đến hạn của bộ để T4 hiển thị kèm ảnh và loại việc.

	Chỉ đọc. Trả ``{"maintenance": [{instrument, instrument_name, image, maint_type, interval,
	cycles_since, deferred_count, state, can_defer}, …]}``; rỗng khi không có gì đến hạn.
	"""
	return {"maintenance": _reminders_from_db(ctx)}


# --- Kiểm tra trước khi sinh Cycle ID ------------------------------------------------------------


def _label(item):
	return f"{item['instrument_name']} ({item['instrument']})"


def _labels(items):
	return ", ".join(_label(item) for item in items)


def _block_items(items):
	return [
		{
			"instrument": item["instrument"],
			"instrument_name": item["instrument_name"],
			"maint_type": item["maint_type"],
			"state": item["state"],
		}
		for item in items
	]


def _oil_lot_block(reason, items):
	return Block(
		"MAINT_OIL_LOT_REQUIRED",
		_("Lubricant lot is required"),
		reason,
		_("Scan the lot code of the lubricant used on this instrument."),
		items=_block_items(items),
	)


def _resolve_oil_batch(raw, item):
	"""``(tên Batch chuẩn, None)`` nếu `raw` là lô của Item nhóm Lubricant, ngược lại ``(None, lý do)``."""
	code = gs1.clean_scan(raw)
	if not code:
		return None, _("Maintenance of {0} is lubrication, but no lubricant lot was entered.").format(
			_label(item)
		)
	batch = frappe.db.get_value("Batch", code, ["name", "item"], as_dict=True)
	if not batch:
		return None, _("Lot {0} does not exist.").format(code)
	if frappe.db.get_value("Item", batch.item, "tc_item_group_cssd") != LUBRICANT_GROUP:
		return None, _("Lot {0} is not a lubricant lot.").format(batch.name)
	return batch.name, None


def check_pack(ctx):
	"""Hook ``tracecore_pack_checks``: ``Block`` đầu tiên gặp, hoặc ``None`` nếu mọi nhắc đã xử lý đúng.

	Thứ tự: (1) nhắc nào chưa có action → ``MAINT_ACTION_REQUIRED`` (liệt kê tất cả); (2) ``overdue`` mà
	action không phải Done → ``MAINT_OVERDUE``; (3) Hoãn không có lý do → ``REASON_REQUIRED``;
	(4) Done cho dụng cụ Lubrication thiếu lô dầu hoặc lô không phải dầu → ``MAINT_OIL_LOT_REQUIRED``.
	Action cho dụng cụ không đến hạn bị bỏ qua.
	"""
	reminders = _reminders(ctx)
	if not reminders:
		return None
	actions = _actions(ctx)

	missing = [item for item in reminders if item["instrument"] not in actions]
	if missing:
		return Block(
			"MAINT_ACTION_REQUIRED",
			_("Maintenance reminder needs an action"),
			_("Maintenance is due and has not been confirmed or deferred: {0}.").format(_labels(missing)),
			_("For each reminder, confirm the maintenance as done, or defer it with a reason."),
			items=_block_items(missing),
		)

	overdue = [
		item
		for item in reminders
		if item["state"] == STATE_OVERDUE and actions[item["instrument"]]["action"] != ACTION_DONE
	]
	if overdue:
		return Block(
			"MAINT_OVERDUE",
			_("Maintenance is overdue"),
			_("Overdue for maintenance and cannot be deferred any more: {0}.").format(_labels(overdue)),
			_("Maintain the instrument, then confirm the maintenance as done."),
			items=_block_items(overdue),
		)

	unexplained = [
		item
		for item in reminders
		if actions[item["instrument"]]["action"] == ACTION_DEFERRED
		and not (actions[item["instrument"]].get("reason") or "").strip()
	]
	if unexplained:
		return Block(
			"REASON_REQUIRED",
			_("Deferral reason is required"),
			_("No reason was entered for deferring the maintenance of: {0}.").format(_labels(unexplained)),
			_("Enter the reason for the deferral, or confirm the maintenance as done."),
			items=_block_items(unexplained),
		)

	for item in reminders:
		action = actions[item["instrument"]]
		if action["action"] != ACTION_DONE or item["maint_type"] != LUBRICATION:
			continue
		_batch, reason = _resolve_oil_batch(action.get("oil_batch"), item)
		if reason:
			return _oil_lot_block(reason, [item])
	return None


# --- Ghi nhận sau khi sinh Cycle ID --------------------------------------------------------------


def _counter_row(set_unit, item):
	"""Dòng Instrument Maintenance của (bộ, dụng cụ), khóa để ghi; chưa có thì dựng mới từ bộ đếm đã nhắc."""
	name = frappe.db.get_value(
		"Instrument Maintenance", {"set_unit": set_unit, "instrument": item["instrument"]}, "name"
	)
	if name:
		return frappe.get_doc("Instrument Maintenance", name, for_update=True)
	return frappe.get_doc(
		{
			"doctype": "Instrument Maintenance",
			"set_unit": set_unit,
			"instrument": item["instrument"],
			"cycles_since_maint": cint(item["cycles_since"]),
			"deferred_count": cint(item["deferred_count"]),
		}
	)


def apply_pack(pack_doc, ctx):
	"""Hook ``tracecore_after_cycle_id``: cập nhật bộ đếm của các nhắc đã được xử lý.

	Done: ``cycles_since_maint`` và ``deferred_count`` về 0, ghi người/thời điểm (và lô dầu nếu Lubrication).
	Deferred: ``deferred_count`` + 1, ghi thời điểm và lý do. Dụng cụ không đến hạn hoặc không có action
	hợp lệ giữ nguyên. Chỉ ghi Instrument Maintenance (Audit Log tự ghi qua doc_events); dòng ``Pack.maint_done``
	do M2 ghi từ chính danh sách action. Giả định ``check_pack`` đã chạy và không trả Block.
	"""
	actions = _actions(ctx)
	if not actions:
		return
	set_unit = ctx["set_unit"]["name"]
	now, user = now_datetime(), frappe.session.user
	for item in _reminders(ctx):
		action = actions.get(item["instrument"])
		if not action:
			continue
		row = _counter_row(set_unit, item)
		if action["action"] == ACTION_DONE:
			if item["maint_type"] == LUBRICATION:
				batch, reason = _resolve_oil_batch(action.get("oil_batch"), item)
				if reason:
					raise BlockedError(_oil_lot_block(reason, [item]))
				row.last_oil_batch = batch
			row.cycles_since_maint = 0
			row.deferred_count = 0
			row.last_maint_on = now
			row.last_maint_by = user
		else:
			row.deferred_count = cint(row.deferred_count) + 1
			row.last_defer_on = now
			row.last_defer_reason = (action.get("reason") or "").strip()
		row.save(ignore_permissions=True)
