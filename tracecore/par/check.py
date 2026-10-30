"""Cơ số tái xử lý của bộ tại T4 và cảnh báo sớm (M8, FEAT-032, FR-M8-03, BRU-PAR-002/003/004).

M2 (đóng gói) không import module này (lint R1): các hàm được khai báo trong ``hooks.py`` và M2 gọi qua
``tracecore.core.extension.run`` — ``pack_context`` (``tracecore_pack_context``) và ``check_pack``
(``tracecore_pack_prechecks``). T3 (FEAT-020) và dashboard gọi ``evaluate`` hoặc RPC ``tracecore.v1.par.check``.

Quy tắc (A-18):

- **Cấp bộ:** ``Set Unit.max_cycles`` (snapshot lúc cấp Set ID); cảnh báo khi còn lại ≤ ``warn_at`` (Q1).
- **Cấp dụng cụ:** chưa có bộ đếm riêng của dụng cụ nên chu trình đã dùng của dụng cụ = ``cycles_used`` của bộ chứa
  nó, cơ số = ``Instrument.max_cycles``, dụng cụ lấy từ BOM phiên bản ghim của chu trình (Q2).
- **Ghi đè:** bộ vượt cơ số nhưng có Par Override hiệu lực (``override.active_for``) thì không chặn (Q9).
- Cơ số 0/trống = Chưa xác định: không chặn, không cảnh báo (UC-31 E3).
- ``check_pack`` là nơi duy nhất chuyển bộ sang Hết vòng đời (qua ``core.step_gate``, Q3).
"""

import math

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import step_gate
from tracecore.core.errors import Block
from tracecore.par import override

DEFAULT_WARN_PERCENT = 10  # SRS FR-M8-03.1: "10 % hoặc 5 lần"
DEFAULT_WARN_COUNT = 5
EOL_REASON = "Par Exceeded"  # lý do ghi vào Audit Log khi bộ sang Hết vòng đời
SET_FIELDS = ("name", "set_type", "status", "cycles_used", "max_cycles", "current_cycle_no")


def warn_at(limit, warn_percent=DEFAULT_WARN_PERCENT, warn_count=DEFAULT_WARN_COUNT):
	"""Số chu trình còn lại mà từ đó cảnh báo sớm: max(ceil(warn_percent % của cơ số), warn_count); cơ số 0 → 0 (Q1)."""
	limit = cint(limit)
	if limit <= 0:
		return 0
	return max(math.ceil(limit * float(warn_percent or 0) / 100), cint(warn_count))


def _thresholds(doctype, target):
	"""``(warn_percent, warn_count)`` của Par Level Reprocessing đang dùng của `target`; không có → mặc định."""
	row = frappe.db.get_value(
		"Par Level",
		{"par_kind": "Reprocessing", "target_doctype": doctype, "target": target, "is_active": 1},
		["warn_percent", "warn_count"],
		as_dict=True,
	)
	if not row:
		return DEFAULT_WARN_PERCENT, DEFAULT_WARN_COUNT
	return row.warn_percent, cint(row.warn_count)


def _unit(set_unit):
	"""Dict trường vòng đời của bộ: nhận dict (ctx của hook, tin giá trị đã đọc) hoặc tên Set Unit."""
	if isinstance(set_unit, dict):
		return set_unit
	return frappe.db.get_value("Set Unit", set_unit, SET_FIELDS, as_dict=True)


def _bom_instruments(unit):
	"""``[{instrument, instrument_name, max_cycles}]`` của BOM phiên bản ghim cho chu trình (0 → hiện hành), có cơ số."""
	pinned = frappe.db.get_value("Set Unit", unit["name"], "cycle_bom_version")
	version = cint(pinned) or cint(
		frappe.db.get_value("Instrument Set Type", unit["set_type"], "current_bom_version")
	)
	codes = frappe.get_all(
		"Set BOM Item", filters={"set_type": unit["set_type"], "bom_version": version}, pluck="instrument"
	)
	if not codes:
		return []
	return frappe.get_all(
		"Instrument",
		filters={"name": ["in", sorted(set(codes))], "max_cycles": [">", 0]},
		fields=["name as instrument", "instrument_name", "max_cycles"],
		order_by="name asc",
	)


def _state(remaining, warn):
	if remaining <= 0:
		return "blocked"
	return "warn" if remaining <= warn else "ok"


def evaluate(set_unit):
	"""Mức dùng cơ số của một bộ (A-18 Q1, Q2, Q13); chỉ đọc.

	`set_unit` là tên Set Unit hoặc dict có ``name``, ``set_type``, ``cycles_used``, ``max_cycles``.
	Trả ``{set_unit, cycles_used, max_cycles, remaining, percent, warn_at, state, instruments, override}``:

	- ``state``: ``undefined`` (cơ số bộ trống và không dụng cụ nào có cơ số), ``ok``, ``warn``, ``blocked``
	  (đã hết cơ số bộ hoặc dụng cụ, không có ghi đè), ``override`` (đã hết nhưng có ghi đè hiệu lực);
	- ``instruments``: dụng cụ ``warn``/``blocked``, mỗi phần tử ``{instrument, instrument_name, max_cycles,
	  remaining, state}``;
	- ``override``: ``{name, extra_cycles, cycles_consumed, valid_until}`` của ghi đè hiệu lực, hoặc None.
	"""
	unit = _unit(set_unit)
	used, limit = cint(unit.get("cycles_used")), cint(unit.get("max_cycles"))
	percent, remaining = (used * 100 // limit, limit - used) if limit > 0 else (0, None)
	percent_warn, count_warn = _thresholds("Instrument Set Type", unit["set_type"]) if limit > 0 else (0, 0)
	set_warn = warn_at(limit, percent_warn, count_warn)
	state = _state(remaining, set_warn) if limit > 0 else "undefined"

	instruments = []
	for row in _bom_instruments(unit):
		left = cint(row.max_cycles) - used
		percent_i, count_i = _thresholds("Instrument", row.instrument)
		level = _state(left, warn_at(row.max_cycles, percent_i, count_i))
		if level != "ok":
			instruments.append({**row, "remaining": max(left, 0), "state": level})
	if any(row["state"] == "blocked" for row in instruments):
		state = "blocked"
	elif instruments and state in ("undefined", "ok"):
		state = "warn"

	active = None
	if state == "blocked":
		active = override.active_for(unit["name"], cint(unit.get("current_cycle_no")))
		state = "override" if active else state
	return {
		"set_unit": unit["name"],
		"cycles_used": used,
		"max_cycles": max(limit, 0),
		"remaining": max(remaining, 0) if remaining is not None else None,
		"percent": percent,
		"warn_at": set_warn,
		"state": state,
		"instruments": instruments,
		"override": active,
	}


def pack_context(ctx):
	"""Hook ``tracecore_pack_context``: mức dùng cơ số cho thanh tiến độ trên T4. Chỉ đọc.

	Trả ``{"par": evaluate(...)}``; giữ các khóa của FEAT-018 (``cycles_used``, ``max_cycles``, ``percent``,
	``state``).
	"""
	return {"par": evaluate(ctx["set_unit"])}


def check_pack(ctx):
	"""Hook ``tracecore_pack_prechecks``: ``PAR_EXCEEDED`` khi bộ hoặc dụng cụ hết cơ số và không có ghi đè hiệu lực.

	Khi chặn: chuyển bộ sang Hết vòng đời qua ``step_gate.end_of_life`` (FR-M8-03.2). Bộ đã Hết vòng đời không bao giờ
	tới đây vì ``step_gate.check`` chặn trước.
	"""
	par = evaluate(ctx["set_unit"])
	if par["state"] != "blocked":
		return None
	name = par["set_unit"]
	step_gate.end_of_life(name, EOL_REASON)
	items = [row for row in par["instruments"] if row["state"] == "blocked"] or None
	pending = override.pending_for(name)
	action = (
		_("Override request {0} is waiting for R01. Do not pack this set until it is approved.").format(
			pending
		)
		if pending
		else _("Do not pack this set. Tap Request override and give the reason; R01 decides.")
	)
	if items:
		reason = _("Set {0} has used {1} cycles; instrument(s) {2} reached their cycle limit.").format(
			name,
			par["cycles_used"],
			", ".join(f"{row['instrument_name']} ({row['instrument']})" for row in items),
		)
	else:
		reason = _("Set {0} has used {1} of {2} reprocessing cycles.").format(
			name, par["cycles_used"], par["max_cycles"]
		)
	return Block("PAR_EXCEEDED", _("Set has reached its cycle limit"), reason, action, items=items)
