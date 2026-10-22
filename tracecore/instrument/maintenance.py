"""Nhắc và kiểm tra bảo dưỡng dụng cụ tại T4 (M1, FEAT-018, FR-M1-09, BRU-REP-014).

M2 (đóng gói) không import module này (lint R1): các hàm được khai báo trong ``hooks.py`` và M2 gọi qua
``tracecore.core.extension.run`` — ``pack_context`` (``tracecore_pack_context``), ``check_pack``
(``tracecore_pack_checks``) và ``apply_pack`` (``tracecore_after_cycle_id``). FEAT-014 thêm ``on_set_released``
(``tracecore_after_release``, FEAT-023 gọi) và ``init_counter`` (RPC ``v1.instrument_admin.init_counters``).

BOM của một bộ = phiên bản áp dụng ``bom_versions.version_for_set_unit`` (FEAT-015 S3): bộ đang trong chu trình dùng
phiên bản đã ghim khi tiếp nhận (FR-M1-04.1), bộ chưa ghim dùng phiên bản hiệu lực.

Ngưỡng là ngưỡng hiệu lực của ``thresholds.effective_rules`` (riêng của dụng cụ → của nhóm, A-06 I5). Bộ đếm
(``Instrument Maintenance``) chỉ ghi qua module này (cờ ``flags.tc_maintenance``).

Quy tắc ngưỡng (D5), so sánh bằng số nguyên để không lệch do số thực:

- không nhắc khi dụng cụ không có ngưỡng hiệu lực, hoặc ``cycles_since < interval``
  (chưa có dòng Instrument Maintenance = 0 chu trình);
- ``due``: ``cycles_since >= interval``;
- ``overdue``: ``due`` và (``cycles_since * 10 > interval * 12``, tức vượt ngưỡng quá 20 %,
  hoặc ``deferred_count >= 3``). Dụng cụ ``overdue`` không còn được hoãn (``can_defer`` False).
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, formatdate, get_datetime, getdate, now_datetime, today

from tracecore.core import gs1
from tracecore.core.errors import Block, BlockedError
from tracecore.instrument import bom, bom_versions, thresholds

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
	"""Nhắc bảo dưỡng của bộ trong ``ctx`` theo BOM áp dụng của bộ (phiên bản ghim), theo thứ tự BOM, mỗi dụng cụ một lần."""
	set_unit = ctx["set_unit"]["name"]
	set_type = ctx["set_type"]
	lines = bom.lines(set_type["name"], cint(bom_versions.version_for_set_unit(set_unit)))
	if not lines:
		return []
	codes = list({line["instrument"] for line in lines})
	# ngưỡng hiệu lực: riêng của dụng cụ → của nhóm → không nhắc (FEAT-014 A-06 I5)
	instruments = thresholds.effective_rules(codes)
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
		interval = instruments[code]["interval"]
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
				"thumbnail": line.get("thumbnail"),
				"maint_type": instruments[code]["maint_type"],
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

	Chỉ đọc. Trả ``{"maintenance": [{instrument, instrument_name, image, thumbnail, maint_type, interval,
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
		row = frappe.get_doc("Instrument Maintenance", name, for_update=True)
	else:
		row = frappe.get_doc(
			{
				"doctype": "Instrument Maintenance",
				"set_unit": set_unit,
				"instrument": item["instrument"],
				"cycles_since_maint": cint(item["cycles_since"]),
				"deferred_count": cint(item["deferred_count"]),
			}
		)
	row.flags.tc_maintenance = True
	return row


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


# --- Khởi tạo bộ đếm và tăng khi giải phóng (FEAT-014 A-06 I6, I16) ------------------------------

MAX_INIT_CYCLES = 9999
MAX_INIT_CYCLES_CHARS = 6  # chuỗi số chu trình dài hơn (kể cả số 0 đầu) bị từ chối trước khi gọi int()
INIT_SAVEPOINT = "tc_maint_init"


def init_block(reason):
	return Block(
		"COUNTER_INIT_INVALID",
		_("Counter cannot be initialized"),
		reason,
		_("Check the set, the number of cycles (0 to {0}) and the date, then try again.").format(
			MAX_INIT_CYCLES
		),
	)


def _init_cycles(value):
	"""Số chu trình 0 đến 9999 (int hoặc chuỗi chữ số ASCII 0-9, tối đa 6 ký tự); khác đi → None.

	Không dùng ``str.isdigit()``: ``'²'``, ``'①'`` qua được nhưng ``int()`` lỗi; chuỗi rất dài làm ``int()`` lỗi
	(giới hạn 4300 chữ số của Python). Mọi giá trị lạ phải thành ``COUNTER_INIT_INVALID`` (422), không 500.
	"""
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		number = value
	elif isinstance(value, str):
		text = value.strip()
		if not (text and len(text) <= MAX_INIT_CYCLES_CHARS and text.isascii() and text.isdecimal()):
			return None
		number = int(text)
	else:
		return None
	return number if 0 <= number <= MAX_INIT_CYCLES else None


def _init_date(value):
	"""Ngày bảo dưỡng gần nhất (tùy chọn): ``(datetime 00:00 | None, lý do lỗi | None)``; không nhận ngày tương lai."""
	if value in (None, ""):
		return None, None
	try:
		day = getdate(value)
	except Exception:
		return None, _("{0} is not a valid date.").format(value)
	if day > getdate(today()):
		return None, _("The last maintenance date {0} is in the future.").format(formatdate(day))
	return get_datetime(day), None


def _has_t4_history(row) -> bool:
	"""Bộ đếm đã có lịch sử: xác nhận bảo dưỡng tại T4 (người xác nhận), lần hoãn, số lần hoãn > 0, hoặc đã đếm một lần
	giải phóng có Cycle ID (``last_release_cycle``, ``on_set_released``): khởi tạo (I6) không được ghi đè số đã đếm.

	Lần giải phóng thiếu ``cycle_id`` (ngoài hợp đồng) không để lại dấu nên không chặn được ở đây.
	"""
	return bool(
		row.last_maint_by
		or row.last_defer_on
		or cint(row.deferred_count) > 0
		or row.get("last_release_cycle")
	)


def _in_current_bom(set_unit_row, instrument) -> bool:
	"""Bộ chứa dụng cụ trong BOM áp dụng của bộ (phiên bản ghim; không ghim → phiên bản hiệu lực)."""
	version = bom_versions.version_for_set_unit(set_unit_row.name)
	return bool(
		frappe.db.exists(
			"Set BOM Item",
			{"set_type": set_unit_row.set_type, "bom_version": cint(version), "instrument": instrument},
		)
	)


def init_counter(set_unit: str, instrument: str, cycles_since, last_maint_on, reason: str) -> str:
	"""Khởi tạo bộ đếm của (bộ, dụng cụ) từ lần bảo dưỡng gần nhất (A-06 I6); trả tên dòng Instrument Maintenance.

	`cycles_since` 0 đến 9999; `last_maint_on` tùy chọn, không ở tương lai; `reason` bắt buộc (ghi vào Audit Log). Bộ phải
	chứa dụng cụ trong BOM áp dụng; dòng đã có lịch sử (đã xác nhận bảo dưỡng tại T4, đã hoãn, đã đếm lần giải
	phóng có Cycle ID) → không khởi tạo được. Lỗi → ``BlockedError`` (``REASON_REQUIRED``, ``SET_NOT_FOUND``, ``INSTRUMENT_NOT_FOUND``,
	``COUNTER_INIT_INVALID``), chưa ghi gì. Không kiểm quyền: RPC ``v1.instrument_admin`` kiểm R02/R10/SM.
	"""
	reason = (reason or "").strip() if isinstance(reason, str) or reason is None else ""
	if not reason:
		raise BlockedError(
			Block(
				"REASON_REQUIRED",
				_("Reason is required"),
				_("A reason is required to initialize a maintenance counter."),
				_("Enter where the cycle count comes from, for example the paper maintenance log."),
			)
		)
	unit = (
		frappe.db.get_value("Set Unit", set_unit, ["name", "set_type"], as_dict=True)
		if isinstance(set_unit, str) and set_unit
		else None
	)
	if not unit:
		raise BlockedError(
			Block(
				"SET_NOT_FOUND",
				_("Set not found"),
				_("Set ID {0} does not exist in TraceCore.").format(set_unit or "-"),
				_("Check the set tag or call R02."),
			)
		)
	if not (isinstance(instrument, str) and instrument and frappe.db.exists("Instrument", instrument)):
		raise BlockedError(
			Block(
				"INSTRUMENT_NOT_FOUND",
				_("Instrument not found"),
				_("Instrument {0} not found.").format(instrument or "-"),
				_("Check the instrument code or call R02."),
			)
		)
	cycles = _init_cycles(cycles_since)
	if cycles is None:
		raise BlockedError(
			init_block(
				_("The number of cycles must be a whole number from 0 to {0}.").format(MAX_INIT_CYCLES)
			)
		)
	maint_on, date_error = _init_date(last_maint_on)
	if date_error:
		raise BlockedError(init_block(date_error))
	if not _in_current_bom(unit, instrument):
		raise BlockedError(
			init_block(
				_("Set {0} does not contain instrument {1} in its current BOM.").format(unit.name, instrument)
			)
		)
	# Dụng cụ Ngừng sử dụng (status Retired) vẫn khởi tạo được: bộ còn chứa nó trong BOM áp dụng thì bộ đếm vẫn có
	# nghĩa ở T4 (FEAT-014 Task 4 fix, quyết định của dev lead; I6 không đặt điều kiện trạng thái dụng cụ).
	name = _counter_name(unit.name, instrument, for_update=True)
	if not name:
		row = frappe.get_doc(
			{
				"doctype": "Instrument Maintenance",
				"set_unit": unit.name,
				"instrument": instrument,
				"cycles_since_maint": cycles,
				"last_maint_on": maint_on,
			}
		)
		row.flags.tc_maintenance = True
		row.flags.tc_audit_reason = reason
		if _try_insert(row):
			return row.name
		# request song song vừa tạo dòng: khóa dòng đó rồi kiểm lịch sử T4 như dòng có sẵn
		name = _counter_name(unit.name, instrument, for_update=True)
	row = frappe.get_doc("Instrument Maintenance", name, for_update=True)
	if _has_t4_history(row):
		raise BlockedError(
			init_block(
				_(
					"Instrument {0} in set {1} already has maintenance history at packing (T4); its counter can no longer be initialized."
				).format(instrument, unit.name)
			)
		)
	row.cycles_since_maint = cycles
	row.last_maint_on = maint_on
	row.flags.tc_maintenance = True
	row.flags.tc_audit_reason = reason
	row.save(ignore_permissions=True)
	return row.name


STATE_NOT_DUE = "not_due"
STATE_NO_RULE = "no_rule"


def instrument_counters(instrument: str, rule: dict | None = None) -> list[dict]:
	"""Bộ đếm bảo dưỡng của một dụng cụ theo từng bộ (form SCR-01, FEAT-014 Task 6); chỉ đọc.

	Gồm mọi dòng ``Instrument Maintenance`` của dụng cụ và mọi bộ chứa dụng cụ trong BOM áp dụng chưa có dòng
	(0 chu trình). Mỗi dòng: ``{set_unit, set_type, cycles_since, deferred_count, state, has_counter, can_init}``;
	``state`` theo quy tắc D5 với ngưỡng hiệu lực `rule` (``no_rule`` / ``not_due`` / ``due`` / ``overdue``);
	``can_init`` = bộ chứa dụng cụ trong BOM áp dụng và chưa có lịch sử T4 (điều kiện của ``init_counter``).
	"""
	interval = cint((rule or {}).get("interval"))
	in_bom = {
		row.name: row.set_type
		for row in frappe.db.sql(
			"""
			select distinct su.name, su.set_type
			from `tabSet Unit` su
			join `tabInstrument Set Type` st on st.name = su.set_type
			join `tabSet BOM Item` line
				on line.set_type = st.name
				and line.bom_version = if(su.cycle_bom_version > 0, su.cycle_bom_version, st.current_bom_version)
			where line.instrument = %s
			""",
			(instrument,),
			as_dict=True,
		)
	}
	rows = {
		row.set_unit: row
		for row in frappe.get_all(
			"Instrument Maintenance",
			filters={"instrument": instrument},
			fields=[
				"set_unit",
				"cycles_since_maint",
				"deferred_count",
				"last_maint_by",
				"last_defer_on",
				"last_release_cycle",
			],
		)
	}
	units = set(in_bom) | set(rows)
	set_types = dict(
		frappe.get_all(
			"Set Unit",
			filters={"name": ["in", list(units - set(in_bom))]},
			fields=["name", "set_type"],
			as_list=True,
		)
		if units - set(in_bom)
		else []
	)
	result = []
	for unit in sorted(units):
		row = rows.get(unit)
		cycles = cint(row.cycles_since_maint) if row else 0
		deferred = cint(row.deferred_count) if row else 0
		if interval <= 0:
			state = STATE_NO_RULE
		else:
			state = _state(interval, cycles, deferred) or STATE_NOT_DUE
		result.append(
			{
				"set_unit": unit,
				"set_type": in_bom.get(unit) or set_types.get(unit),
				"cycles_since": cycles,
				"deferred_count": deferred,
				"state": state,
				"has_counter": bool(row),
				"can_init": unit in in_bom and not (row and _has_t4_history(row)),
			}
		)
	return result


def _counter_name(set_unit, instrument, for_update=False):
	return frappe.db.get_value(
		"Instrument Maintenance",
		{"set_unit": set_unit, "instrument": instrument},
		"name",
		for_update=for_update,
	)


def _try_insert(row) -> bool:
	"""Insert dòng Instrument Maintenance mới trong savepoint; trùng (request song song vừa tạo) → hoàn tác, ``False``."""
	frappe.db.savepoint(INIT_SAVEPOINT)
	try:
		row.insert(ignore_permissions=True)
		return True
	except frappe.DuplicateEntryError:
		frappe.db.rollback(save_point=INIT_SAVEPOINT)
		frappe.clear_last_message()
		return False


def on_set_released(ctx: dict) -> None:
	"""Hook ``tracecore_after_release`` (FR-M1-09.2, A-06 I16): mẻ giải phóng Đạt → +1 chu trình cho bộ.

	Hợp đồng: ``ctx = {"set_unit", "set_type", "bom_version", "cycle_id"}``; ``cycle_id`` (Cycle ID của gói được giải
	phóng) là **bắt buộc**. ``bom_version`` = BOM áp dụng của gói; thiếu thì lấy BOM áp dụng của bộ (phiên bản ghim). Mỗi dụng cụ khác nhau có
	ngưỡng hiệu lực được +1 ``cycles_since_maint`` đúng một lần (số lượng trong BOM không tính); chưa có dòng thì tạo với
	1. Dụng cụ không ngưỡng không tạo dòng. Khóa dòng ``for_update``. FEAT-023 gọi qua ``tracecore.core.extension.run``.

	Chống đếm hai lần: dòng đã đếm ``cycle_id`` này (``last_release_cycle``) thì bỏ qua, nên FEAT-023 thử lại bước giải
	phóng của cùng Cycle ID không cộng thêm. Chỉ so với lần giải phóng **gần nhất** của bộ (một bộ chỉ có một chu trình
	đang chạy, nên gọi lại Cycle ID cũ sau khi Cycle ID mới đã được đếm là lỗi của nơi gọi). Thiếu ``cycle_id`` (rỗng):
	giữ hành vi cũ, +1 mỗi lần gọi, không chống trùng — nơi gọi phải gọi đúng một lần cho mỗi lần giải phóng.
	"""
	set_unit, set_type = ctx["set_unit"], ctx["set_type"]
	cycle_id = cstr(ctx.get("cycle_id")).strip() or None
	version = ctx.get("bom_version")
	if version is None:
		version = bom_versions.version_for_set_unit(set_unit)
	codes = []
	for line in bom.lines(set_type, cint(version)):
		if line["instrument"] not in codes:
			codes.append(line["instrument"])
	rules = thresholds.effective_rules(codes)
	for code in codes:
		if code not in rules:
			continue
		_increment(set_unit, code, cycle_id)


def _increment(set_unit, instrument, cycle_id=None):
	name = _counter_name(set_unit, instrument, for_update=True)
	if not name:
		row = frappe.get_doc(
			{
				"doctype": "Instrument Maintenance",
				"set_unit": set_unit,
				"instrument": instrument,
				"cycles_since_maint": 1,
				"last_release_cycle": cycle_id,
			}
		)
		row.flags.tc_maintenance = True
		if _try_insert(row):
			return
		# request song song vừa tạo dòng: khóa dòng đó rồi cộng như bình thường (kể cả kiểm Cycle ID)
		name = _counter_name(set_unit, instrument, for_update=True)
	row = frappe.get_doc("Instrument Maintenance", name, for_update=True)
	if cycle_id and row.last_release_cycle == cycle_id:
		return  # lần giải phóng này đã được đếm
	row.cycles_since_maint = cint(row.cycles_since_maint) + 1
	if cycle_id:
		row.last_release_cycle = cycle_id
	row.flags.tc_maintenance = True
	row.save(ignore_permissions=True)
