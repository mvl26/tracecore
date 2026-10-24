"""Tóm tắt và lịch sử vòng đời Set Unit (FEAT-016 Task 6; FR-M1-06, FR-M1-06.2; AC-6, AC-7; A-09 G13).

Không có hook hay bảng lịch sử riêng: mọi đổi trường vòng đời đã đi qua ``step_gate._save_lifecycle`` → Audit Log
``Update`` của Set Unit với tên sự kiện ở cột lý do (``issue``, ``start_cycle``, ``gate T2 Fail``, ``bind_cycle``,
``release_cycle``, ``dispose: <lý do>``). `history` gộp bốn nguồn đọc theo tên DocType — Audit Log của Set Unit,
`Step Gate Result`, `Print Job` (``ref_doctype = Set Unit``), `Pack` — mới → cũ, phân trang theo con trỏ
``"<thời điểm>|<loại>|<tên>"``: thứ tự toàn phần (thời điểm, loại, tên) nên trang sau nối đúng trang trước, không trùng,
không sót kể cả khi nhiều sự kiện cùng một thời điểm. Số truy vấn cố định (≤ 5: kiểm bộ + một truy vấn mỗi nguồn).
`set_units` công bố lại `summary`, `history` (giao diện của plan).
"""

import frappe
from frappe import _
from frappe.utils import cint, get_datetime

from tracecore.core import step_gate
from tracecore.core.errors import BlockedError
from tracecore.instrument import bom_versions, set_tags

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
CURSOR_SEPARATOR = "|"
DETAIL_MAX = 300
EMPTY = "—"
# Thứ tự trong cùng một thời điểm (mới → cũ: loại lớn trước) và loại có tên số (autoincrement)
KIND_RANK = {"audit": 0, "gate": 1, "print": 2, "pack": 3}
INT_NAMES = ("audit", "print")
SUMMARY_FIELDS = [
	"name",
	"set_type",
	"department",
	"status",
	"cycles_used",
	"max_cycles",
	"cycles_source",
	"active_cycle_id",
	"current_station",
	"cycle_bom_version",
	"tag_verified_on",
	"tag_verified_by",
]

# nguồn → (bảng, biểu thức thời điểm, điều kiện theo bộ, cột)
SOURCES = {
	"audit": (
		"`tabAudit Log`",
		"timestamp",
		"ref_doctype = 'Set Unit' and ref_name = %(unit)s",
		"user, action, old_value, new_value, reason",
	),
	"gate": (
		"`tabStep Gate Result`",
		"coalesce(recorded_at, creation)",
		"set_unit = %(unit)s",
		"recorded_by as user, step, result, cycle_no, redo_count, station",
	),
	"print": (
		"`tabPrint Job`",
		"creation",
		"ref_doctype = 'Set Unit' and ref_name = %(unit)s",
		"owner as user, status, printer, data, reprint_reason, error",
	),
	"pack": (
		"`tabPack`",
		"creation",
		"set_unit = %(unit)s",
		"coalesce(packed_by_user, owner) as user, status, cycle_no",
	),
}


def _unit_row(set_unit, fields):
	row = (
		frappe.db.get_value("Set Unit", set_unit, fields, as_dict=True)
		if isinstance(set_unit, str) and set_unit
		else None
	)
	if not row:
		raise BlockedError(set_tags.not_found_block(set_unit))
	return row


def summary(set_unit: str) -> dict:
	"""Tóm tắt form Set Unit (FR-M1-06.2, AC-7): chu trình đã dùng / tối đa / còn lại ``max(0, tối đa - đã dùng)``, nguồn
	số chu trình (``Actual``/``Estimated``), Cycle ID hiệu lực, phiên bản BOM (ghim, hoặc phiên bản hiệu lực "sẽ ghim khi
	tiếp nhận"), quét kiểm tra thẻ, trạng thái mã trong Code Registry, số lần in. Bộ không có → ``SET_NOT_FOUND``."""
	row = _unit_row(set_unit, SUMMARY_FIELDS)
	used, maximum = cint(row.cycles_used), cint(row.max_cycles)
	return {
		"set_id": row.name,
		"set_type": row.set_type,
		"set_type_name": frappe.db.get_value("Instrument Set Type", row.set_type, "set_type_name"),
		"department": row.department,
		"status": row.status,
		"cycles_used": used,
		"max_cycles": maximum,
		"remaining": max(0, maximum - used),
		"cycles_source": row.cycles_source,
		"active_cycle_id": row.active_cycle_id or None,
		"current_station": row.current_station or None,
		"cycle_bom_version": cint(row.cycle_bom_version),
		"bom_version_applied": bom_versions.version_for_set_unit(row.name),
		"bom_pinned": cint(row.cycle_bom_version) > 0,
		"tag_verified_on": row.tag_verified_on,
		"tag_verified_by": row.tag_verified_by,
		"code_status": frappe.db.get_value("Code Registry", row.name, "status"),
		"print_counts": set_tags.print_counts(row.name),
	}


# --- Lịch sử ------------------------------------------------------------------------------------------------------


def _limit(limit) -> int:
	if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
		frappe.throw(_("limit must be a whole number from 1 to {0}.").format(MAX_LIMIT))
	return limit


def parse_cursor(before):
	"""``(thời điểm, loại | None, tên | None)`` từ `before` (con trỏ ``next_before`` hoặc chỉ thời điểm); sai → lỗi."""
	if before in (None, ""):
		return None
	invalid = _("before must be a history cursor or a date and time.")
	if not isinstance(before, str):
		frappe.throw(invalid)
	parts = before.split(CURSOR_SEPARATOR)
	try:
		at = get_datetime(parts[0])
	except Exception:
		at = None
	if not at or len(parts) not in (1, 3):
		frappe.throw(invalid)
	if len(parts) == 1:
		return at, None, None
	kind, name = parts[1], parts[2]
	if kind not in KIND_RANK or not name or (kind in INT_NAMES and not name.isdigit()):
		frappe.throw(invalid)
	return at, kind, int(name) if kind in INT_NAMES else name


def _page_condition(kind, at_expr, cursor):
	"""Điều kiện "cũ hơn con trỏ" theo thứ tự (thời điểm, loại, tên) giảm dần."""
	if not cursor:
		return ""
	_at, cursor_kind, _name = cursor
	if cursor_kind is None or KIND_RANK[kind] > KIND_RANK[cursor_kind]:
		return f" and {at_expr} < %(at)s"
	if KIND_RANK[kind] < KIND_RANK[cursor_kind]:
		return f" and {at_expr} <= %(at)s"
	return f" and ({at_expr} < %(at)s or ({at_expr} = %(at)s and name < %(name)s))"


def _rows(kind, set_unit, cursor, limit):
	table, at_expr, condition, columns = SOURCES[kind]
	params = {"unit": set_unit, "n": limit + 1}
	if cursor:
		params.update(at=cursor[0], name=cursor[2])
	return frappe.db.sql(
		f"""
		select name, {at_expr} as at, {columns} from {table}
		where {condition}{_page_condition(kind, at_expr, cursor)}
		order by {at_expr} desc, name desc limit %(n)s
		""",  # nosec B608 - chỉ chèn tên bảng/cột cố định của SOURCES
		params,
		as_dict=True,
	)


def _json(value):
	data = frappe.parse_json(value) if value else {}
	return data if isinstance(data, dict) else {}


def _text(value):
	return EMPTY if value in (None, "") else str(value)


def _clip(text):
	return text if len(text) <= DETAIL_MAX else text[: DETAIL_MAX - 1] + "…"


AUDIT_TITLES = {
	step_gate.ISSUE_EVENT: lambda: _("Set ID issued"),
	"start_cycle": lambda: _("Cycle started"),
	"bind_cycle": lambda: _("Cycle ID bound"),
	"release_cycle": lambda: _("Cycle ID released"),
	set_tags.VERIFY_REASON: lambda: _("Tag verified"),
	"export": lambda: _("Exported for engraving"),
}


def _audit_event(row):
	if row.action == "Reject":
		return {"event": "reject", "title": _("Rejected"), "detail": _text(row.reason), "reason": None}
	event, reason = step_gate.split_event(row.reason)
	if event in AUDIT_TITLES:
		title = AUDIT_TITLES[event]()
	elif event and event.startswith("gate "):
		_gate, step, result = [*event.split(" "), "", ""][:3]
		title = _("Step gate {0}: {1}").format(step, _(result, context="Step Gate Result"))
	else:
		title = {"Create": _("Created"), "Update": _("Updated")}.get(row.action) or _(row.action)
	old, new = _json(row.old_value), _json(row.new_value)
	if row.action == "Update":
		detail = ", ".join(
			f"{field}: {_text(old.get(field))} → {_text(value)}" for field, value in new.items()
		)
	else:
		detail = ", ".join(
			f"{field}: {_text(value)}" for field, value in new.items() if value not in (None, "")
		)
	return {
		"event": event or row.action.lower(),
		"title": title,
		"detail": _clip(detail),
		"reason": reason,
	}


def _gate_event(row):
	detail = _("Cycle {0}, redo count {1}").format(cint(row.cycle_no), cint(row.redo_count))
	if row.station:
		detail += ", " + _("station {0}").format(row.station)
	return {
		"event": f"{row.step} {row.result}",
		"title": _("Step {0}: {1}").format(row.step, _(row.result, context="Step Gate Result")),
		"detail": detail,
		"reason": None,
	}


def _print_event(row):
	data = _json(row.data)
	kind = data.get("kind") if data.get("kind") in set_tags.KINDS else None
	reprint = bool(data.get("reprint"))
	if kind:
		label = _(set_tags.KINDS[kind], context="Label Template")
		title = (_("{0}: reprint") if reprint else _("{0}: print")).format(label)
		event = f"{kind} {'reprint' if reprint else 'print'}"
	else:
		title, event = _("Print job"), "print"
	detail = _("Status {0}, printer {1}").format(_(row.status, context="Print Job"), _text(row.printer))
	if row.error:
		detail += ": " + str(row.error)
	return {"event": event, "title": title, "detail": _clip(detail), "reason": row.reprint_reason or None}


def _pack_event(row):
	return {
		"event": "pack",
		"title": _("Packed: {0}").format(row.name),
		"detail": _("Cycle {0}, status {1}").format(cint(row.cycle_no), _(row.status, context="Pack")),
		"reason": None,
	}


BUILDERS = {"audit": _audit_event, "gate": _gate_event, "print": _print_event, "pack": _pack_event}


def _sort_key(item):
	kind, row = item
	return row.at, KIND_RANK[kind], row.name


def history(set_unit: str, before: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
	"""Lịch sử vòng đời của bộ, mới → cũ (FR-M1-06, AC-6; G13).

	Trả ``{"events": [{at, kind: audit|gate|print|pack, title, detail, user, reason, event, ref}], "next_before"}``;
	``event`` là mã máy đọc (vd ``gate T2 Fail``, ``T2 Pass``, ``tag reprint``, ``dispose``), ``ref`` tên bản ghi nguồn,
	``reason`` lý do người dùng (thanh lý, in lại). ``next_before`` = con trỏ của sự kiện cuối khi còn sự kiện cũ hơn,
	ngược lại None. `before`: con trỏ đó, hoặc chỉ một thời điểm (mọi sự kiện trước nó). `limit` 1-``MAX_LIMIT``;
	tham số sai → ValidationError; bộ không có → ``BlockedError(SET_NOT_FOUND)``. Tối đa 5 truy vấn.
	"""
	limit = _limit(limit)
	cursor = parse_cursor(before)
	unit = _unit_row(set_unit, ["name"]).name
	merged = [(kind, row) for kind in SOURCES for row in _rows(kind, unit, cursor, limit)]
	merged.sort(key=_sort_key, reverse=True)
	page = merged[:limit]
	events = [
		{
			"at": row.at,
			"kind": kind,
			"user": row.user,
			"ref": str(row.name),
			**BUILDERS[kind](row),
		}
		for kind, row in page
	]
	next_before = None
	if len(merged) > limit and page:
		kind, row = page[-1]
		next_before = CURSOR_SEPARATOR.join((str(row.at), kind, str(row.name)))
	return {"events": events, "next_before": next_before}
