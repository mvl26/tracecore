"""Cơ số tái xử lý của bộ tại T4 (M8, FEAT-018 stub, FR-M8-03, BRU-PAR-002).

M2 (đóng gói) không import module này (lint R1): các hàm được khai báo trong ``hooks.py`` và M2 gọi qua
``tracecore.core.extension.run`` — ``pack_context`` (``tracecore_pack_context``) và ``check_pack``
(``tracecore_pack_prechecks``). Đề nghị ghi đè cơ số và chuyển Set Unit sang Hết vòng đời là FEAT-032.

Dữ liệu lấy từ ``ctx["set_unit"]``: ``name``, ``cycles_used``, ``max_cycles``. Set Unit luôn có
``max_cycles`` > 0; thiếu hoặc 0 thì coi như không đặt giới hạn (không chia cho 0, không chặn).
"""

from frappe import _
from frappe.utils import cint

from tracecore.core.errors import Block

WARN_PERCENT = 90  # từ 90 % cơ số trở lên: cảnh báo (state "warn")


def _usage(ctx):
	"""``(cycles_used, max_cycles, percent)``; percent làm tròn xuống, không giới hạn trên."""
	set_unit = ctx["set_unit"]
	used, limit = cint(set_unit.get("cycles_used")), cint(set_unit.get("max_cycles"))
	if limit <= 0:
		return used, 0, 0
	return used, limit, used * 100 // limit


def pack_context(ctx):
	"""Hook ``tracecore_pack_context``: mức dùng cơ số cho thanh tiến độ trên T4.

	Chỉ đọc. Trả ``{"par": {cycles_used, max_cycles, percent, state}}``, ``state`` là ``blocked`` khi
	``cycles_used >= max_cycles``, ``warn`` khi từ 90 %, còn lại ``ok``.
	"""
	used, limit, percent = _usage(ctx)
	if limit and used >= limit:
		state = "blocked"
	elif percent >= WARN_PERCENT:
		state = "warn"
	else:
		state = "ok"
	return {"par": {"cycles_used": used, "max_cycles": limit, "percent": percent, "state": state}}


def check_pack(ctx):
	"""Hook ``tracecore_pack_prechecks``: ``PAR_EXCEEDED`` khi bộ đã dùng hết cơ số, ngược lại ``None``."""
	used, limit, _percent = _usage(ctx)
	if not limit or used < limit:
		return None
	return Block(
		"PAR_EXCEEDED",
		_("Set has reached its cycle limit"),
		_("Set {0} has used {1} of {2} reprocessing cycles.").format(ctx["set_unit"]["name"], used, limit),
		_("Do not pack this set. The override request will be available from FEAT-032."),
	)
