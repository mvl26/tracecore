"""Ngưỡng bảo dưỡng hiệu lực theo dụng cụ hoặc nhóm (M1, FEAT-014; FR-M1-09, .1; A-06 I5; Review Focus 4).

Ngưỡng hiệu lực của một dụng cụ = ngưỡng riêng (``Instrument.maint_interval_cycles`` > 0, kèm loại việc của dụng
cụ) → ngưỡng của ``Instrument Group`` (> 0, kèm loại việc của nhóm) → không có (FR-M1-09.1: trống ở cả hai thì
không nhắc). Mỗi dụng cụ một quy tắc, lấy trọn từ một nguồn. Quy tắc D5 (``maintenance._state``) không đổi.

Đổi ngưỡng/nhóm không bao giờ đụng bộ đếm (``Instrument Maintenance``); chỉ cảnh báo các bộ sẽ chuyển sang
đến hạn/quá hạn ở lần đóng gói tới.
"""

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.utils import cint, escape_html

SOURCE_INSTRUMENT = "Instrument"
SOURCE_GROUP = "Group"


def _rule(interval, maint_type, source):
	return {"interval": cint(interval), "maint_type": maint_type or None, "source": source}


def rule_of(instrument, group=None) -> dict | None:
	"""Quy tắc hiệu lực của một dụng cụ (dict/Document có ``maint_interval_cycles``, ``maint_type``) và nhóm của nó."""
	if cint(instrument.get("maint_interval_cycles")) > 0:
		return _rule(instrument.get("maint_interval_cycles"), instrument.get("maint_type"), SOURCE_INSTRUMENT)
	if group and cint(group.get("maint_interval_cycles")) > 0:
		return _rule(group.get("maint_interval_cycles"), group.get("maint_type"), SOURCE_GROUP)
	return None


def _groups(names) -> dict:
	names = [name for name in set(names) if name]
	if not names:
		return {}
	return {
		row.name: row
		for row in frappe.get_all(
			"Instrument Group",
			filters={"name": ["in", names]},
			fields=["name", "maint_interval_cycles", "maint_type"],
		)
	}


def effective_rules(codes: Iterable[str]) -> dict[str, dict]:
	"""``{mã: {interval, maint_type, source}}`` cho các dụng cụ có ngưỡng hiệu lực; dụng cụ không có ngưỡng bị bỏ."""
	codes = list({code for code in codes or () if code})
	if not codes:
		return {}
	rows = frappe.get_all(
		"Instrument",
		filters={"name": ["in", codes]},
		fields=["name", "maint_interval_cycles", "maint_type", "instrument_group"],
	)
	groups = _groups(row.instrument_group for row in rows if cint(row.maint_interval_cycles) <= 0)
	rules = {}
	for row in rows:
		rule = rule_of(row, groups.get(row.instrument_group))
		if rule:
			rules[row.name] = rule
	return rules


def _group_members(group) -> list[str]:
	"""Dụng cụ thuộc nhóm và đang thừa hưởng ngưỡng nhóm (không có ngưỡng riêng)."""
	return frappe.get_all(
		"Instrument",
		filters={"instrument_group": group, "maint_interval_cycles": ["<=", 0]},
		pluck="name",
		order_by="name asc",
	)


def affected_counters(
	instrument: str | None = None, group: str | None = None, new_rule: dict | None = None
) -> list[dict]:
	"""Các bộ đếm sẽ ở trạng thái ``due``/``overdue`` (theo ``maintenance._state``) dưới quy tắc `new_rule`.

	`instrument`: bộ đếm của dụng cụ đó; `group`: bộ đếm của các dụng cụ thừa hưởng ngưỡng nhóm. `new_rule` None →
	quy tắc hiện có trong DB; ``{"interval": 0}`` = không có ngưỡng. Mỗi dòng: ``{set_unit, instrument,
	cycles_since, deferred_count, interval, state}``, sắp theo bộ rồi dụng cụ. Chỉ đọc.
	"""
	from tracecore.instrument import maintenance  # maintenance import module này (ngưỡng cho T4)

	if instrument:
		codes = [instrument]
		rule = new_rule if new_rule is not None else effective_rules(codes).get(instrument)
	elif group:
		codes = _group_members(group)
		rule = new_rule if new_rule is not None else rule_of({}, _groups([group]).get(group))
	else:
		return []
	interval = cint((rule or {}).get("interval"))
	if interval <= 0 or not codes:
		return []
	rows = frappe.get_all(
		"Instrument Maintenance",
		filters={"instrument": ["in", codes]},
		fields=["set_unit", "instrument", "cycles_since_maint", "deferred_count"],
		order_by="set_unit asc, instrument asc",
	)
	result = []
	for row in rows:
		cycles, deferred = cint(row.cycles_since_maint), cint(row.deferred_count)
		state = maintenance._state(interval, cycles, deferred)
		if state:
			result.append(
				{
					"set_unit": row.set_unit,
					"instrument": row.instrument,
					"cycles_since": cycles,
					"deferred_count": deferred,
					"interval": interval,
					"state": state,
				}
			)
	return result


def _instrument_rule(doc) -> dict | None:
	return rule_of(doc, _groups([doc.get("instrument_group")]).get(doc.get("instrument_group")))


def _state_label(state):
	return _("overdue for maintenance") if state == "overdue" else _("due for maintenance")


def warn_rule_change(doc) -> list[dict] | None:
	"""Gọi trong ``on_update`` của ``Instrument``/``Instrument Group``: cảnh báo khi quy tắc hiệu lực đổi.

	Liệt kê các bộ mà trạng thái nhắc trở nên nặng hơn (chưa đến hạn → đến hạn/quá hạn, đến hạn → quá hạn) do
	ngưỡng giảm, ngưỡng mới khai báo hoặc đổi nhóm. Không đổi bộ đếm. Kết quả cũng đặt vào
	``doc.flags.tc_affected_counters``; None khi quy tắc không đổi (hoặc bản ghi mới).
	"""
	from tracecore.instrument import maintenance

	before = doc.get_doc_before_save()
	if not before:
		return None
	if doc.doctype == "Instrument":
		old, new = _instrument_rule(before), _instrument_rule(doc)
		if old == new:
			return None
		rows = affected_counters(instrument=doc.name, new_rule=new or {"interval": 0})
	else:
		old, new = rule_of({}, before), rule_of({}, doc)
		if old == new:
			return None
		rows = affected_counters(group=doc.name, new_rule=new or {"interval": 0})
	old_interval = cint((old or {}).get("interval"))
	worse = [
		row
		for row in rows
		if row["state"] != maintenance._state(old_interval, row["cycles_since"], row["deferred_count"])
	]
	doc.flags.tc_affected_counters = worse
	if worse:
		lines = "".join(
			"<li>{}</li>".format(
				escape_html(
					_("Set {0}, instrument {1}: {2} cycles of {3}, {4}").format(
						row["set_unit"],
						row["instrument"],
						row["cycles_since"],
						row["interval"],
						_state_label(row["state"]),
					)
				)
			)
			for row in worse
		)
		frappe.msgprint(
			"{}<ul>{}</ul>{}".format(
				escape_html(_("After this change, these sets need maintenance at the next packing:")),
				lines,
				escape_html(_("Cycle counters are kept; nothing was reset.")),
			),
			title=_("Maintenance threshold changed"),
			indicator="orange",
		)
	return worse
