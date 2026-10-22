"""RPC vòng đời Set Unit: ngữ cảnh form, lịch sử, thanh lý (FEAT-016 Task 6; FR-M1-06, FR-M1-06.2, FR-M1-05.2;
BRU-ID-001; A-09 G7, G13, G14).

Đường RPC công khai giữ ``tracecore.v1.set_unit.<action>`` như plan: `tracecore.v1.set_unit` nhập lại ba hàm này (Frappe
tra đường chấm bằng ``getattr`` trên module và so hàm với danh sách whitelist, nên cùng một hàm whitelist được ở cả hai
đường). Tách file để `set_unit.py` không vượt giới hạn độ dài; các tuple role của cả hai module đặt ở đây.

- `form_context` (GET): tóm tắt bộ (`set_units.summary`), giới hạn nghiệp vụ cho JS (không chép hằng số), quyền theo
  role, loại bản in, máy in gợi ý (đang hoạt động, có địa chỉ mạng).
- `history` (GET): `set_units.history`, phân trang bằng ``next_before``.
- `dispose` (POST, ``@idempotent``): TC R02 / System Manager, lý do bắt buộc (G14).
"""

import frappe
from frappe import _

from tracecore.core import print_server
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.instrument import set_history, set_tags, set_units
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

ISSUE_ROLES = ("TC R02", "TC R10", "System Manager")  # cấp, in, in lại, hủy lệnh in, xuất CSV (G7)
VERIFY_ROLES = (*ISSUE_ROLES, "TC R04")  # quét kiểm tra thẻ (UC-03 bước 4)
DISPOSE_ROLES = ("TC R02", "System Manager")  # thanh lý (G7, G14)
MAX_NAME_CHARS = 140
MAX_LIMIT_CHARS = 3
PRINTERS_HINT_MAX = 50


def _set_id(value, required=True):
	if value in (None, "") and not required:
		return None
	if not isinstance(value, str) or not value.strip() or len(value) > MAX_NAME_CHARS:
		raise BadRequestError(_("{0} must be a non-empty text.").format("set_unit"))
	return value.strip()


def _limit(value):
	"""`limit` 1-``set_history.MAX_LIMIT`` dạng int hoặc chuỗi chữ số (query string GET); sai → 400."""
	if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
		value = int(value.strip()) if len(value.strip()) <= MAX_LIMIT_CHARS else 0
	if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= set_history.MAX_LIMIT:
		raise BadRequestError(_("limit must be a whole number from 1 to {0}.").format(set_history.MAX_LIMIT))
	return value


def _printers_hint():
	"""Máy in đang hoạt động gửi được từ server (thẻ/nhãn khay chỉ in qua đường server, ``PRINTER_NOT_NETWORK``)."""
	rows = frappe.get_all(
		"Printer",
		filters={"is_active": 1, "host": ["is", "set"]},
		fields=["name", "printer_name", "station"],
		order_by="name asc",
		limit=PRINTERS_HINT_MAX,
	)
	return [row for row in rows if print_server.printer_address(row.name) is not None]


@frappe.whitelist(methods=["GET"])
def form_context(set_unit=None):
	"""Ngữ cảnh form Set Unit / hộp thoại Cấp Set ID (FR-M1-06.2; G7): ``{ok, summary, limits, permissions, kinds,
	printers_hint}``. ``summary`` None khi không truyền bộ; bộ không có → ``SET_NOT_FOUND`` (404, Audit ``Reject`` được
	commit dù là GET)."""
	frappe.has_permission("Set Unit", "read", throw=True)
	set_unit = _set_id(set_unit, required=False)
	roles = set(frappe.get_roles())
	can_issue = bool(roles & set(ISSUE_ROLES))
	summary = None
	if set_unit:
		try:
			summary = set_units.summary(set_unit)
		except BlockedError as error:
			return reject_block(error.block, "Set Unit", set_unit)
	return {
		"ok": True,
		"summary": summary,
		"limits": {
			"max_batch": set_units.MAX_BATCH,
			"reason_max": set_tags.REASON_MAX,
			"max_cycles_limit": set_units.MAX_CYCLES_LIMIT,
		},
		"permissions": {
			"can_issue": can_issue,
			"can_print": can_issue,
			"can_reprint": can_issue,
			"can_verify": bool(roles & set(VERIFY_ROLES)),
			"can_dispose": bool(roles & set(DISPOSE_ROLES)),
		},
		"kinds": [
			{"kind": kind, "label_object": label, "label": _(label, context="Label Template")}
			for kind, label in set_tags.KINDS.items()
		],
		"printers_hint": _printers_hint() if can_issue else [],
	}


@frappe.whitelist(methods=["GET"])
def history(set_unit=None, before=None, limit=set_history.DEFAULT_LIMIT):
	"""Lịch sử vòng đời của bộ, mới → cũ (FR-M1-06; G13): ``{ok, events, next_before}``.

	`before` = ``next_before`` của trang trước (hoặc một thời điểm); `limit` 1-200; tham số sai → 400; bộ không có →
	``SET_NOT_FOUND`` (404, Audit ``Reject`` được commit)."""
	frappe.has_permission("Set Unit", "read", throw=True)
	set_unit = _set_id(set_unit)
	limit = _limit(limit)
	try:
		set_history.parse_cursor(before)
	except frappe.ValidationError:
		raise BadRequestError(_("before must be a history cursor or a date and time.")) from None
	try:
		result = set_units.history(set_unit, before or None, limit)
	except BlockedError as error:
		return reject_block(error.block, "Set Unit", set_unit)
	return {"ok": True, **result}


@frappe.whitelist(methods=["POST"])
@idempotent
def dispose(set_unit, reason=None, client_ts=None):
	"""Thanh lý bộ Mới tạo / Hết vòng đời (G14; FR-M1-05.2, BRU-ID-001): ``{ok, set_unit, status}``.

	Role kiểm trước mọi ghi (``DISPOSE_ROLES``; R10, R04 → PermissionError, không để lại Idempotency Key/Audit). Lý do
	1-500 ký tự (``REASON_REQUIRED`` 422); trạng thái khác hoặc còn Cycle ID → ``STATUS_INVALID_FOR_ACTION`` (409);
	bộ không có → ``SET_NOT_FOUND`` (404). Mã Set ID thành ``Disabled``: vẫn tra được, không in được, không cấp lại."""
	require_any_role(*DISPOSE_ROLES)
	timestamp = parse_client_ts(client_ts)
	set_unit = _set_id(set_unit)
	try:
		result = set_units.dispose(set_unit, reason)
	except BlockedError as error:
		return reject_block(error.block, "Set Unit", set_unit, client_ts=timestamp)
	return {"ok": True, **result}
