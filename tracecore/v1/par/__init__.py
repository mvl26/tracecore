"""RPC tracecore.v1.par.* — kiểm cơ số của bộ (M8, FEAT-032, FR-M8-03.1): chỉ đọc, cho T3, T4, dashboard.

``check(set_id)`` trả mức dùng cơ số của một bộ (``tracecore.par.check.evaluate``); không có ``set_id`` thì trả danh sách
bộ đang cảnh báo / bị chặn / đang ghi đè (nguồn cho widget dashboard SCR-32 của FEAT-006 và báo cáo dự báo thay thế
của FEAT-007). Hiển thị cảnh báo cam trên SCR-07 (T3) do FEAT-020 gọi ``par.check.evaluate`` qua hook.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.par import check as par_check
from tracecore.v1._common import BadRequestError

STATES = ("warn", "blocked", "override", "ok", "undefined")
DEFAULT_STATES = ("warn", "blocked", "override")
MAX_SCAN = 500  # số bộ nhiều chu trình nhất được đánh giá cho một lần gọi danh sách
LIST_FIELDS = ["name", "set_type", "status", "cycles_used", "max_cycles", "current_cycle_no", "department"]


def _states(value):
	if value is None:
		return DEFAULT_STATES
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			value = [value]
	if not isinstance(value, list) or not value or any(state not in STATES for state in value):
		raise BadRequestError(_("states must be a list of: {0}.").format(", ".join(STATES)))
	return tuple(value)


@frappe.whitelist(methods=["GET", "POST"])
def check(set_id=None, states=None, limit=100):
	"""Mức dùng cơ số: một bộ (``set_id``) → ``{"ok", "par"}``; bỏ trống → ``{"ok", "sets": [...]}`` (xem module)."""
	frappe.has_permission("Set Unit", "read", throw=True)
	if set_id:
		if not isinstance(set_id, str) or not frappe.db.exists("Set Unit", set_id):
			frappe.throw(_("Set Unit {0} not found.").format(set_id), frappe.DoesNotExistError)
		frappe.has_permission("Set Unit", "read", doc=set_id, throw=True)
		return {"ok": True, "par": par_check.evaluate(set_id)}
	wanted, limit = _states(states), max(1, min(cint(limit) or 100, 500))
	rows = frappe.get_all(
		"Set Unit",
		filters={"status": ["not in", ["New", "Disposed"]], "max_cycles": [">", 0]},
		fields=LIST_FIELDS,
		order_by="name asc",
	)
	# bộ gần hết cơ số nhất trước; chỉ đánh giá MAX_SCAN bộ đầu để một lần gọi không quét cả kho bộ
	rows.sort(key=lambda row: cint(row.cycles_used) / cint(row.max_cycles), reverse=True)
	names, sets = {}, []
	for row in rows[:MAX_SCAN]:
		par = par_check.evaluate(dict(row))
		if par["state"] not in wanted:
			continue
		if row.set_type not in names:
			names[row.set_type] = frappe.db.get_value("Instrument Set Type", row.set_type, "set_type_name")
		sets.append({**par, "status": row.status, "set_type": row.set_type, "set_name": names[row.set_type]})
		if len(sets) >= limit:
			break
	return {"ok": True, "sets": sets}
