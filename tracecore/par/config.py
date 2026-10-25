"""Cấu hình cơ số tái xử lý và cơ số tồn khoa (M8, FEAT-031, FR-M8-01, FR-M8-02, UC-30, OTH-RET-002).

``Par Level`` là nguồn sự thật cơ số tái xử lý (A-11 S1): lưu Par Level của một dụng cụ đồng bộ một chiều sang
``Instrument.max_cycles`` để M1/M2 và ``par.check`` đọc như cũ. Par Level của loại bộ **không** ghi vào Set Unit
(``max_cycles`` là snapshot lúc cấp Set ID, FEAT-016/032). Module này không import M1-M10: đọc ``Instrument``,
``Set Unit``, ``Set BOM Item`` theo tên DocType.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, now_datetime

from tracecore.core import audit

KIND_REPROCESSING = "Reprocessing"
KIND_STOCK = "Department Stock"
REPROCESSING_TARGETS = ("Instrument", "Instrument Set Type")
STOCK_TARGETS = ("Instrument Set Type",)
MAX_OVER_PERCENT = 20  # khoa cấp cứu được vượt tối đa 20 % không cần duyệt (BRU-PAR-005)
TRACKED_FIELDS = (
	"max_cycles",
	"source",
	"warn_percent",
	"warn_count",
	"min_qty",
	"max_qty",
	"over_percent",
	"is_emergency_dept",
	"is_active",
)
REASON_FIELDS = ("max_cycles", "min_qty", "max_qty")  # đổi các trường này phải có lý do (FR-M8-01.3)
HISTORY_FIELDS = ("changed_by", "changed_on", "field_name", "old_value", "new_value", "reason")


def validate(doc) -> None:
	"""Luật của một Par Level; gọi từ ``ParLevel.validate``."""
	_normalize(doc)
	_check_target(doc)
	_check_unique(doc)
	_check_values(doc)
	_check_below_used(doc)
	_record_history(doc)


def _normalize(doc) -> None:
	doc.max_cycles = cint(doc.max_cycles)
	doc.warn_count = cint(doc.warn_count)
	doc.min_qty = cint(doc.min_qty)
	doc.max_qty = cint(doc.max_qty)
	doc.warn_percent = flt(doc.warn_percent)
	doc.over_percent = flt(doc.over_percent)
	doc.is_emergency_dept = cint(doc.is_emergency_dept)
	doc.is_active = cint(doc.is_active)
	if doc.par_kind == KIND_REPROCESSING:
		doc.department = None
		doc.min_qty = doc.max_qty = 0
		doc.over_percent = 0
		doc.is_emergency_dept = 0
	else:
		doc.max_cycles = 0
		doc.confirm_below_used = 0


def _check_target(doc) -> None:
	allowed = REPROCESSING_TARGETS if doc.par_kind == KIND_REPROCESSING else STOCK_TARGETS
	if doc.target_doctype not in allowed:
		frappe.throw(
			_("{0} cannot be used as the target of a {1} par level.").format(
				_(doc.target_doctype or ""), _(doc.par_kind or "")
			)
		)
	if not frappe.db.exists(doc.target_doctype, doc.target):
		frappe.throw(_("{0} {1} does not exist.").format(_(doc.target_doctype), doc.target))
	if doc.par_kind == KIND_STOCK and not doc.department:
		frappe.throw(_("Department is required for a department stock par level."))


def _check_unique(doc) -> None:
	filters = {
		"par_kind": doc.par_kind,
		"target_doctype": doc.target_doctype,
		"target": doc.target,
		"department": doc.department or ["is", "not set"],
	}
	if doc.name:
		filters["name"] = ["!=", doc.name]
	existing = frappe.db.get_value("Par Level", filters, "name")
	if existing:
		frappe.throw(_("Par level {0} already exists for this target.").format(existing))


def _check_values(doc) -> None:
	if doc.max_cycles < 0 or doc.warn_count < 0 or doc.min_qty < 0 or doc.max_qty < 0:
		frappe.throw(_("Par level values cannot be negative."))
	if not 0 <= doc.warn_percent <= 100:
		frappe.throw(_("Early warning percent must be between 0 and 100."))
	if doc.par_kind != KIND_STOCK:
		return
	if doc.min_qty > doc.max_qty:  # FR-M8-02.3
		frappe.throw(
			_("Minimum ({0}) cannot be greater than maximum ({1}).").format(doc.min_qty, doc.max_qty)
		)
	if not 0 <= doc.over_percent <= MAX_OVER_PERCENT:
		frappe.throw(_("Allowed overshoot must be between 0 and {0} percent.").format(MAX_OVER_PERCENT))
	if doc.over_percent > 0 and not doc.is_emergency_dept:
		frappe.throw(_("Only an emergency department may be allowed to exceed its maximum."))


def used_cycles(doc) -> int | None:
	"""Số chu trình đã dùng nhiều nhất của đối tượng; ``None`` khi chưa có bộ đếm (dụng cụ, G4)."""
	if doc.target_doctype != "Instrument Set Type":
		return None
	rows = frappe.get_all(
		"Set Unit", filters={"set_type": doc.target}, fields=["max(cycles_used) as used"], limit=1
	)
	return cint(rows[0].used) if rows else 0


def _check_below_used(doc) -> None:
	"""FR-M8-01.4: cơ số ≤ chu trình đã dùng → cảnh báo trước khi lưu (lưu được sau khi xác nhận)."""
	if doc.par_kind != KIND_REPROCESSING or doc.max_cycles <= 0:
		return
	before = doc.get_doc_before_save()
	if before is not None and cint(before.max_cycles) == doc.max_cycles:
		return
	used = used_cycles(doc)
	if used is not None and doc.max_cycles <= used and not cint(doc.confirm_below_used):
		frappe.throw(
			_(
				"Cycle limit {0} is not above the {1} cycles already used. Tick Confirm to save it anyway."
			).format(doc.max_cycles, used)
		)
	doc.confirm_below_used = 0


def _text(value) -> str:
	if value is None:
		return ""
	if isinstance(value, float | int) and not isinstance(value, bool) and value == int(value):
		return str(int(value))
	return cstr(value)


def _record_history(doc) -> None:
	"""Thêm một dòng ``Par Level History`` cho mỗi trường đổi; lịch sử đã lưu bất biến (FR-M8-01.3, OTH-RET-002)."""
	before = doc.get_doc_before_save()
	_guard_history(doc, before)
	changed = []
	for field in TRACKED_FIELDS:
		old, new = _text(before.get(field)) if before else "", _text(doc.get(field))
		if (before is not None and old != new) or (before is None and new not in ("", "0")):
			changed.append((field, old, new))
	reason = cstr(doc.reason).strip()
	if before is not None and any(field in REASON_FIELDS for field, _old, _new in changed) and not reason:
		frappe.throw(_("A reason is required when the par level changes."))
	now = now_datetime()
	for field, old, new in changed:
		doc.append(
			"history",
			{
				"changed_by": frappe.session.user,
				"changed_on": now,
				"field_name": field,
				"old_value": old,
				"new_value": new,
				"reason": reason or None,
			},
		)
	doc.reason = None


def _guard_history(doc, before) -> None:
	if before is None:
		return
	saved = {row.name: row for row in before.get("history") or []}
	current = {row.name: row for row in doc.get("history") or [] if row.name in saved}
	if set(saved) - set(current):
		frappe.throw(_("Par level history cannot be removed."))
	for name, row in current.items():
		if any(cstr(row.get(f)) != cstr(saved[name].get(f)) for f in HISTORY_FIELDS):
			frappe.throw(_("Par level history cannot be changed."))


def sync_instrument(doc) -> None:
	"""Ghi ``Instrument.max_cycles`` theo Par Level đang hiệu lực (S1); Audit Log ghi cả hai phía."""
	if doc.par_kind != KIND_REPROCESSING or doc.target_doctype != "Instrument" or not cint(doc.is_active):
		return
	new = {
		"max_cycles": cint(doc.max_cycles),
		"max_cycles_status": "Defined" if cint(doc.max_cycles) > 0 else "Undefined",
	}
	old = frappe.db.get_value("Instrument", doc.target, list(new), as_dict=True)
	if not old or all(cstr(old[key]) == cstr(value) for key, value in new.items()):
		return
	frappe.db.set_value("Instrument", doc.target, dict(new))  # set_value thêm modified vào dict truyền vào
	audit.log(
		"Update",
		"Instrument",
		doc.target,
		old={key: old[key] for key in new},
		new=new,
		reason=_("Par Level {0}").format(doc.name),
	)


def effective_set_type_cap(set_type: str) -> dict:
	"""Cơ số bộ: Par Level riêng của loại bộ, nếu không thì min cơ số dụng cụ trong BOM hiệu lực (FR-M8-01.2).

	``{value, source: "Par Level" | "Derived" | "Undefined", undefined: [mã dụng cụ chưa có cơ số]}``;
	``undefined`` luôn rỗng khi dùng Par Level riêng.
	"""
	own = cint(
		frappe.db.get_value(
			"Par Level",
			{
				"par_kind": KIND_REPROCESSING,
				"target_doctype": "Instrument Set Type",
				"target": set_type,
				"is_active": 1,
			},
			"max_cycles",
		)
	)
	if own > 0:
		return {"value": own, "source": "Par Level", "undefined": []}
	version = frappe.db.get_value("Instrument Set Type", set_type, "current_bom_version")
	codes = frappe.get_all(
		"Set BOM Item", filters={"set_type": set_type, "bom_version": cint(version)}, pluck="instrument"
	)
	rows = (
		frappe.get_all("Instrument", filters={"name": ["in", codes]}, fields=["name", "max_cycles"])
		if codes
		else []
	)
	caps = [cint(row.max_cycles) for row in rows if cint(row.max_cycles) > 0]
	undefined = sorted(row.name for row in rows if cint(row.max_cycles) <= 0)
	if caps:
		return {"value": min(caps), "source": "Derived", "undefined": undefined}
	return {"value": None, "source": "Undefined", "undefined": undefined}


def set_type_cap(ctx: dict) -> dict:
	"""Hook ``tracecore_set_type_cap`` cho M1 cấp Set ID (FEAT-016, A-13 G5): ``{value, source}`` của loại bộ."""
	cap = effective_set_type_cap(ctx["set_type"])
	return {"value": cap["value"], "source": cap["source"]}
