"""Cơ số tồn khoa khi cấp phát T7 (M8, FEAT-026 C5, FR-M2-16, FR-M8-02, BRU-PAR-005).

M2 (cấp phát) không import module này: ``issue_par`` khai báo trong ``hooks.py`` là ``tracecore_issue_par_check`` và M2
gọi qua ``tracecore.core.extension.run``. Module này đọc ``Par Level`` loại ``Department Stock`` theo tên DocType.
"""

import frappe
from frappe.utils import cint, flt

from tracecore.par.config import KIND_STOCK


def _par_level(department, set_type):
	return frappe.db.get_value(
		"Par Level",
		{
			"par_kind": KIND_STOCK,
			"target_doctype": "Instrument Set Type",
			"target": set_type,
			"department": department,
			"is_active": 1,
		},
		["min_qty", "max_qty", "over_percent", "is_emergency_dept"],
		as_dict=True,
	)


def issue_par(ctx):
	"""Hook ``tracecore_issue_par_check``: so tồn khoa + số gói cấp với cơ số khoa của một loại bộ.

	``ctx``: ``{department, set_type, stock, adding}``. Trả ``{state, min, max, over_percent, limit, stock, adding,
	after, suggest}``; ``state``: ``unconfigured`` (chưa có cơ số đang hiệu lực, FR-M2-16.4), ``over`` (vượt tối đa,
	cần R02 duyệt, FR-M2-16.1), ``over_allowed`` (khoa cấp cứu vượt trong % cho phép, FR-M2-16.3), ``ok``.
	``limit`` = floor(max * (100 + over_percent) / 100); ``suggest`` = số gói còn thiếu để đạt tối thiểu khi tồn khoa
	đang dưới tối thiểu (FR-M2-16.2), 0 nếu không.
	"""
	stock, adding = cint(ctx.get("stock")), cint(ctx.get("adding"))
	after = stock + adding
	result = {
		"set_type": ctx.get("set_type"),
		"stock": stock,
		"adding": adding,
		"after": after,
		"min": None,
		"max": None,
		"over_percent": 0,
		"limit": None,
		"suggest": 0,
	}
	par = _par_level(ctx.get("department"), ctx.get("set_type"))
	if not par:
		return {**result, "state": "unconfigured"}
	low, high, over_percent = cint(par.min_qty), cint(par.max_qty), flt(par.over_percent)
	emergency = cint(par.is_emergency_dept) and over_percent > 0
	limit = int(high * (100 + over_percent) // 100) if emergency else high
	if after <= high:
		state = "ok"
	elif after <= limit:
		state = "over_allowed"
	else:
		state = "over"
	return {
		**result,
		"state": state,
		"min": low,
		"max": high,
		"over_percent": over_percent if emergency else 0,
		"limit": limit,
		"suggest": max(0, low - after) if stock < low else 0,
	}
