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
	**dict.fromkeys(("SESSION_INVALID", "SESSION_EXPIRED", "SESSION_IDLE"), 401),
	**dict.fromkeys(
		(
			"CARD_INVALID",
			"COMPETENCY_REQUIRED",
			"PIN_INVALID",
			"PIN_PROOF_INVALID",
			"SESSION_STATION_MISMATCH",
		),
		403,
	),
	**dict.fromkeys(("PIN_LOCKED", "LOGIN_THROTTLED"), 429),
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
			"ETCHING_INVALID",
			"IMPORT_ROWS_INVALID",
			"IMPORT_FILE_INVALID",
			"PIN_FORMAT_INVALID",
			# FEAT-015 A-09 (S4, S5, S7): loại bộ / phiên bản BOM / hạn lưu loại gói
			"BOM_EMPTY",
			"BOM_LINE_INVALID",
			"BOM_TOO_LARGE",
			"BOM_EFFECTIVE_DATE_INVALID",
			"SHELF_LIFE_INVALID",
			# FEAT-016 A-09 (G5, G6, G16): điều kiện cấp Set ID hàng loạt
			"SET_TYPE_BOM_INVALID",
			"DEPARTMENT_INVALID",
			"MAX_CYCLES_INVALID",
			# FEAT-016 ruling Task 4/5: thẻ/nhãn khay Set ID chỉ in qua đường server (máy in phải có địa chỉ mạng)
			"PRINTER_NOT_NETWORK",
			# FEAT-021 A-12: lô rửa T2
			"EQUIPMENT_NOT_WASHER",
			"PROGRAM_INVALID",
			"CHEMICAL_LOT_INVALID",
			"CHEMICAL_LOT_EXPIRED",
			"BATCH_EMPTY",
			"DATA_INCOMPLETE",
			"RESULT_INVALID",
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
			"SET_TYPE_NOT_FOUND",
			"BOM_VERSION_NOT_FOUND",
			"WASH_BATCH_NOT_FOUND",
			"LOCATION_NOT_FOUND",
		),
		404,
	),
	# 423: máy rửa không Sẵn sàng (Khóa/Sửa chữa/Ngừng sử dụng), theo BA API-M2-02/03 (FEAT-021 A-12, Q21).
	"EQUIPMENT_NOT_READY": 423,
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
			"PACK_NOT_RELEASED",
			"PACK_EXPIRED",
			"PACK_NOT_IN_STOCK",
			"PACK_ALREADY_ON_LOCATION",
			"LOCATION_INACTIVE",
			"ROLL_PRINTER_AMBIGUOUS",
			"STATION_INACTIVE",
			"EQUIPMENT_NOT_RETIRABLE",
			"EQUIPMENT_RETIRED",
			"PROGRAM_CODE_EXISTS",
			"CODE_DISABLED",
			"INSTRUMENT_RETIRED",
			"INSTRUMENT_IN_BOM",
			"FEATURE_DISABLED",
			"GIAI_ALREADY_ASSIGNED",
			"GIAI_NOT_ASSIGNED",
			"GS1_PREFIX_NOT_CONFIGURED",
			"COMPANY_NOT_CONFIGURED",
			"BOM_VERSION_CONFLICT",
			"SET_TYPE_CODE_EXISTS",
			# FEAT-016: series Set ID của loại bộ đã hết dải 999 999 (G2) — không cấp mã 7 số
			"SET_SERIES_EXHAUSTED",
			# FEAT-016 G10, G12: bộ đã thanh lý, lệnh in cùng loại đang chờ, thẻ quét không khớp bộ
			"SET_DISPOSED",
			"TAG_PRINT_PENDING",
			"TAG_MISMATCH",
			"STEP_ALREADY_PASSED",
			"SET_IN_OTHER_BATCH",
			"BATCH_NOT_RUNNING",
			"EQUIPMENT_MISMATCH",
			"R02_CONFIRM_REQUIRED",
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
