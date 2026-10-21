"""Từ chối nghiệp vụ của trạm/PDA: `Block` và bảng mã HTTP (FEAT-018 D3, implementation-plan §5.5).

Một nơi duy nhất quyết định mã HTTP theo loại lỗi; body RPC là ``{"ok": false, "error": block.as_dict()}``.
Thứ tự nội dung theo design.md §6: kết quả (title) → lý do (reason) → hành động (action).
"""

from dataclasses import dataclass

import frappe

# 422: đúng cú pháp nhưng dữ liệu sai; 404: không tìm thấy; 409: xung đột trạng thái nghiệp vụ.
# 400 (sai định dạng) và 403 (thiếu quyền) không phải Block: do IdempotencyKeyError, ClientTimestampError,
# thiếu tham số và frappe.PermissionError đảm nhiệm.
HTTP_STATUS: dict[str, int] = {
	**dict.fromkeys(
		(
			"STATION_WRONG_STEP",
			"SCAN_INVALID",
			"BOM_INCOMPLETE",
			"CI_LOT_INVALID",
			"CI_LOT_EXPIRED",
			"PACK_TYPE_INVALID",
			"REASON_REQUIRED",
			"MAINT_ACTION_REQUIRED",
			"MAINT_OIL_LOT_REQUIRED",
			"ROLL_NOT_LABEL",
			"LABEL_RENDER_FAILED",
			"PROGRAM_MODEL_MISMATCH",
			"PROGRAM_COPY_INVALID",
			"COUNT_OUT_OF_RANGE",
			"COUNTER_INIT_INVALID",
		),
		422,
	),
	**dict.fromkeys(
		(
			"SET_NOT_FOUND",
			"PACK_NOT_FOUND",
			"ROLL_NOT_FOUND",
			"EQUIPMENT_NOT_FOUND",
			"CODE_NOT_FOUND",
			"INSTRUMENT_NOT_FOUND",
		),
		404,
	),
	**dict.fromkeys(
		(
			"STATUS_INVALID_FOR_STATION",
			"ACTIVE_CYCLE_EXISTS",
			"GATE_PREV_NOT_PASSED",
			"SET_TYPE_GTIN_MISSING",
			"PAR_EXCEEDED",
			"MAINT_OVERDUE",
			"REPRINT_WINDOW_EXPIRED",
			"PACK_NOT_VOIDABLE",
			"ROLL_PRINTER_AMBIGUOUS",
			"STATION_INACTIVE",
			"EQUIPMENT_NOT_RETIRABLE",
			"EQUIPMENT_RETIRED",
			"PROGRAM_CODE_EXISTS",
			"CODE_DISABLED",
			"INSTRUMENT_RETIRED",
			"INSTRUMENT_IN_BOM",
		),
		409,
	),
}
DEFAULT_HTTP_STATUS = 409


@dataclass
class Block:
	"""Một từ chối nghiệp vụ: mã máy đọc được + ba câu cho người dùng (đã qua ``_()`` khi dựng)."""

	code: str
	title: str
	reason: str
	action: str
	items: list | None = None
	redo_step: str | None = None

	@property
	def http_status(self) -> int:
		return HTTP_STATUS.get(self.code, DEFAULT_HTTP_STATUS)

	def as_dict(self) -> dict:
		data = {
			"code": self.code,
			"title": self.title,
			"reason": self.reason,
			"action": self.action,
			"http_status": self.http_status,
			"items": self.items,
			"redo_step": self.redo_step,
		}
		return {key: value for key, value in data.items() if value is not None}


class BlockedError(frappe.ValidationError):
	"""Ngoại lệ mang `Block` để tầng RPC đổi thành body lỗi + mã HTTP; `str(error)` là lý do."""

	def __init__(self, block: Block):
		super().__init__(block.reason)
		self.block = block
		self.http_status_code = block.http_status
