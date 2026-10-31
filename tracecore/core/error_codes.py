"""Khung mã lỗi (FEAT-052, A-71): tra mã từ `Block.code`, cấu hình theo viện và Nhật ký lỗi.

`Block.code` giữ nguyên làm mã máy đọc được (JS và test dựa vào); mã `<NHÓM>-<3 số>` nằm trên nó, tra qua trường
`block_codes` của `TraceCore Error Code`. Cấu hình đọc từ Single đã cache, Frappe xóa cache khi lưu nên đổi là có hiệu lực ngay.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, getdate, now_datetime

from tracecore.core import client_time

CODE_DOCTYPE = "TraceCore Error Code"
LOG_DOCTYPE = "TraceCore Error Log"
SETTINGS = "TraceCore Settings"
BLOCK, WARNING, INFO = "Block", "Warning", "Info"
OPEN, RESOLVED, ALLOWED = "Open", "Resolved", "Temporarily Allowed"
_BLOCK_MAP_KEY = "tracecore_error_block_map"

# Không thuộc danh mục: lỗi nhập liệu, không tìm thấy, xác thực và lỗi chứng từ, không phải kiểm soát an toàn hay quy trình.
# Thêm mã `Block` mới phải chọn: gán vào `setup.error_codes` hoặc ghi vào đây (test_every_block_code_mapped_or_excluded).
UNMAPPED_BLOCK_CODES = frozenset(
	{
		"ASSEMBLY_CLOSED",
		"ASSEMBLY_NOT_FOUND",
		"BATCH_EMPTY",
		"BI_NOT_PENDING",
		"BOM_EFFECTIVE_DATE_INVALID",
		"BOM_EMPTY",
		"BOM_LINE_INVALID",
		"BOM_TOO_LARGE",
		"BOM_VERSION_CONFLICT",
		"BOM_VERSION_NOT_FOUND",
		"BRANCH_INVALID",
		"CAPA_ACTIONS_OPEN",
		"CAPA_ACTION_INCOMPLETE",
		"CAPA_ACTION_REQUIRED",
		"CARD_INVALID",
		"CERTIFICATE_TYPE_INVALID",
		"CODE_DISABLED",
		"CODE_NOT_FOUND",
		"CODE_RANGE_EXHAUSTED",
		"CODE_RANGE_INVALID",
		"COMPANY_NOT_CONFIGURED",
		"COMPETENCY_EXISTS",
		"COMPETENCY_INVALID",
		"COMPETENCY_NOT_ACTIVE",
		"COMPETENCY_NOT_ALLOWED",
		"COST_SOURCE_NOT_FOUND",
		"COUNTER_INIT_INVALID",
		"COUNT_OUT_OF_RANGE",
		"DELIVERER_NAME_REQUIRED",
		"DELIVERER_NOT_FOUND",
		"DELIVERER_NO_DEPARTMENT",
		"DEPARTMENT_INVALID",
		"DEPARTMENT_NOT_FOUND",
		"DISPOSAL_NOT_ALLOWED",
		"DISPOSAL_NOT_ELIGIBLE",
		"DISPOSAL_NOT_PENDING",
		"DISPOSAL_PENDING",
		"EMPLOYEE_INVALID",
		"ENV_READING_INVALID",
		"ENV_ZONE_NOT_MONITORED",
		"EQUIPMENT_NOT_FOUND",
		"EQUIPMENT_NOT_RETIRABLE",
		"ERROR_CODE_NOT_FOUND",
		"ETCHING_INVALID",
		"EXTRA_CYCLES_INVALID",
		"FEATURE_DISABLED",
		"FEEDBACK_INVALID",
		"FEEDBACK_RATE_LIMIT",
		"FORCE_NOT_ALLOWED",
		"GIAI_ALREADY_ASSIGNED",
		"GIAI_NOT_ASSIGNED",
		"GS1_PREFIX_NOT_CONFIGURED",
		"GS1_PREFIX_NOT_DECLARED",
		"GTIN_BACKFILL_STALE",
		"GTIN_NOT_LOCKED",
		"GTIN_RANGE_EXHAUSTED",
		"IMPORT_FILE_INVALID",
		"IMPORT_ROWS_INVALID",
		"INCIDENT_LINK_REQUIRED",
		"INCIDENT_NOT_ALLOWED",
		"INCIDENT_STATUS_INVALID",
		"INSTRUMENT_IN_BOM",
		"INSTRUMENT_NOT_FOUND",
		"INSTRUMENT_RETIRED",
		"ISSUE_EMPTY",
		"ISSUE_ITEM_INVALID",
		"ISSUE_NOT_DRAFT",
		"ISSUE_NOT_FOUND",
		"ISSUE_NOT_SIGNED",
		"ISSUE_QTY_INVALID",
		"ISSUE_COMPANY_AMBIGUOUS",
		"ITEM_NOT_CONFIRMED",
		"LABEL_RENDER_FAILED",
		"LAUNDRY_CHEMICAL_INVALID",
		"LAUNDRY_DRY_INVALID",
		"LAUNDRY_MIXED",
		"LAUNDRY_NOT_FOUND",
		"LAUNDRY_NOT_RUNNING",
		"LAUNDRY_REDO_INVALID",
		"LAUNDRY_RESULT_REQUIRED",
		"LAUNDRY_VENDOR_REQUIRED",
		"LAUNDRY_WEIGHT_INVALID",
		"LINEN_EMPTY",
		"LINEN_ISSUE_KIND_INVALID",
		"LINEN_QTY_INVALID",
		"LINEN_RECIPIENT_INVALID",
		"LINEN_SIGNATURE_INVALID",
		"LINEN_TOTAL_INVALID",
		"LINEN_TYPE_INVALID",
		"LINEN_VARIANCE_NOTE_REQUIRED",
		"LOAD_EMPTY",
		"LOAD_NOT_FOUND",
		"LOANER_DATES_INVALID",
		"LOANER_GTIN_IN_USE",
		"LOANER_NOT_ALLOWED",
		"LOANER_NOT_RECEIVED",
		"LOANER_NOT_REPROCESSED",
		"LOANER_RETURN_QTY_INVALID",
		"LOCATION_INACTIVE",
		"LOCATION_NOT_FOUND",
		"LOGIN_THROTTLED",
		"LOT_INVALID",
		"MACHINE_CYCLE_UNMATCHED",
		"MACHINE_DATA_EXISTS",
		"MACHINE_NOT_AT_STATION",
		"MACHINE_NOT_CONNECTED",
		"MANUAL_REASON_REQUIRED",
		"MAX_CYCLES_INVALID",
		"NOTE_REQUIRED",
		"NO_SHORTAGE",
		"OVERRIDE_NOT_FOUND",
		"OVERRIDE_NOT_PENDING",
		"OVERRIDE_PENDING",
		"OWN_PIN_RESET",
		"PACK_ALREADY_ON_LOCATION",
		"PACK_NOT_FOUND",
		"PACK_NOT_VOIDABLE",
		"PACK_TYPE_INVALID",
		"PAR_NOT_EXCEEDED",
		"PATIENT_CODE_ALREADY_SET",
		"PATIENT_CODE_UNREADABLE",
		"PERMISSION_DENIED",
		"PERMIT_INVALID",
		"PHOTO_INVALID",
		"PIN_CHANGE_REQUIRED",
		"PIN_FORMAT_INVALID",
		"PIN_INVALID",
		"PIN_LOCKED",
		"PIN_PROOF_INVALID",
		"PIN_REUSED",
		"PRINTER_NOT_NETWORK",
		"PROGRAM_CODE_EXISTS",
		"PROGRAM_COPY_INVALID",
		"PROGRAM_MODEL_MISMATCH",
		"PURCHASE_ITEM_INVALID",
		"PURCHASE_NOT_NEEDED",
		"QTY_INVALID",
		"RATE_VERSION_NOT_APPROVED",
		"REASON_REQUIRED",
		"RECALL_EMPTY",
		"RECALL_EXISTS",
		"RECALL_INCOMPLETE",
		"RECALL_LINE_DONE",
		"RECALL_NOT_ALLOWED",
		"RECALL_NOT_OPEN",
		"RECALL_PACK_NOT_FOUND",
		"RECEIPT_CLOSED",
		"RECEIPT_EMPTY",
		"RECEIPT_NOT_FOUND",
		"RECIPIENT_INVALID",
		"REPRINT_WINDOW_EXPIRED",
		"RESULT_INVALID",
		"RESULT_REQUIRED",
		"ROLL_NOT_FOUND",
		"ROLL_NOT_LABEL",
		"ROLL_PRINTER_AMBIGUOUS",
		"ROOT_CAUSE_REQUIRED",
		"SCAN_INVALID",
		"SCAN_WRONG_TYPE",
		"SCREENSHOT_INVALID",
		"SELF_APPROVAL_NOT_ALLOWED",
		"SESSION_EXPIRED",
		"SESSION_IDLE",
		"SESSION_INVALID",
		"SESSION_STATION_MISMATCH",
		"SET_DISPOSED",
		"SET_NOT_FOUND",
		"SET_SERIES_EXHAUSTED",
		"SET_TYPE_BOM_INVALID",
		"SET_TYPE_CODE_EXISTS",
		"SET_TYPE_GTIN_MISSING",
		"SET_TYPE_NOT_FOUND",
		"SHARPS_DETAILS_REQUIRED",
		"SHELF_LIFE_INVALID",
		"SIGNATURE_INVALID",
		"STATION_INACTIVE",
		"STATION_INVALID",
		"STATUS_INVALID",
		"STOCK_INSUFFICIENT",
		"TAG_MISMATCH",
		"TAG_PRINT_PENDING",
		"TEMP_TOO_LONG",
		"TICKET_REQUIRED",
		"TRANSITION_NOT_ALLOWED",
		"UNLOCK_INVALID",
		"USAGE_NOT_FOUND",
		"VALID_UNTIL_INVALID",
		"VERIFICATION_REQUIRED",
		"VOID_REASON_REQUIRED",
		"WASH_BATCH_NOT_FOUND",
		"WASTE_BAG_ALREADY_ON_HANDOVER",
		"WASTE_BAG_NOT_STORED",
		"WASTE_CONTAINER_UNKNOWN",
		"WASTE_DOCUMENT_REQUIRED",
		"WASTE_EMPTY",
		"WASTE_FIFO_REASON",
		"WASTE_GIVER_INVALID",
		"WASTE_HANDOVER_EMPTY",
		"WASTE_HANDOVER_INVALID",
		"WASTE_LOCATION_INVALID",
		"WASTE_NOTE_REQUIRED",
		"WASTE_NOTHING_TO_STORE",
		"WASTE_NOT_COLD_ROOM",
		"WASTE_NOT_HELD",
		"WASTE_NOT_STORABLE",
		"WASTE_NO_DEFAULT_LOCATION",
		"WASTE_QTY_INVALID",
		"WASTE_SIGNATURE_REQUIRED",
		"WASTE_TEMPERATURE_INVALID",
		"WASTE_THRESHOLD_INVALID",
		"WASTE_TOTAL_INVALID",
		"WASTE_TYPE_INVALID",
		"WASTE_VARIANCE_APPROVAL",
		"WASTE_VARIANCE_REASON",
		"WASTE_VENDOR_NOT_PERMITTED",
		"WASTE_WEIGHT_MISSING",
		"WASTE_WEIGHT_UNCONFIRMED",
		"WASTE_WRONG_LOCATION",
	}
)


def clear_cache() -> None:
	frappe.cache.delete_value(_BLOCK_MAP_KEY)
	frappe.clear_document_cache(SETTINGS, SETTINGS)


def _block_map() -> dict:
	def build():
		rows = frappe.get_all(CODE_DOCTYPE, fields=["name", "block_codes"])
		return {code: row.name for row in rows for code in (row.block_codes or "").split() if code}

	return frappe.cache.get_value(_BLOCK_MAP_KEY, generator=build)


def error_code_of(block_code: str, explicit: str | None = None) -> str | None:
	if explicit:
		return explicit
	try:
		return _block_map().get(block_code)
	except Exception as error:
		# code mới, chưa migrate: thiếu bảng không được biến mọi lời từ chối thành lỗi 500
		if frappe.db.is_table_missing(error):
			return None
		raise


def catalog_of(block_code: str, explicit: str | None = None) -> dict | None:
	"""Mã, tên và việc có hướng dẫn của một từ chối; None nếu là lỗi nhập liệu không thuộc danh mục."""
	code = error_code_of(block_code, explicit)
	row = code and frappe.db.get_value(CODE_DOCTYPE, code, ["error_name", "guide"], as_dict=True)
	if not row:
		return None
	return {"error_code": code, "error_name": _(row.error_name), "has_guide": bool(row.guide)}


def pack_error_code(pack) -> str | None:
	"""CT-001 khi gói bị chặn do chỉ thị/chu trình của mẻ, BI chờ hoặc thu hồi; khác đi là sai trạng thái (QT-001)."""
	if pack.status in ("Quarantine", "Recalled"):
		return "CT-001"
	if pack.status == "Void" and pack.get("void_reason") == "Load Failed":
		return "CT-001"
	return None


def rule_of(code: str) -> dict | None:
	"""Cấu hình hiệu lực của mã: bật/tắt, mức độ, số ngày cảnh báo, vai trò duyệt; None nếu mã không có."""
	row = frappe.db.get_value(CODE_DOCTYPE, code, ["default_severity", "severity_locked"], as_dict=True)
	if not row:
		return None
	settings = frappe.get_cached_doc(SETTINGS)
	rule = next((item for item in settings.get("error_rules") or [] if item.error_code == code), None)
	locked = bool(cint(row.severity_locked))
	return {
		# mã khóa luôn theo mặc định, kể cả khi thiếu dòng cấu hình hoặc dòng bị sửa bằng đường khác
		"enabled": True if locked or not rule else bool(cint(rule.enabled)),
		"severity": row.default_severity
		if locked
		else (rule.severity if rule else None) or row.default_severity,
		"warn_days": cint(rule.warn_days) if rule else 0,
		"approver_roles": (rule.approver_roles or "").split("\n") if rule and rule.approver_roles else [],
		"locked": locked,
	}


def validate_rules(settings) -> None:
	"""Mã bị khóa không đổi mức độ, không tắt được; vai trò duyệt phải có thật (FR-M9-18)."""
	for rule in settings.get("error_rules") or []:
		row = frappe.db.get_value(
			CODE_DOCTYPE, rule.error_code, ["default_severity", "severity_locked"], as_dict=True
		)
		if not row:
			continue
		if cint(row.severity_locked) and (not cint(rule.enabled) or rule.severity != row.default_severity):
			frappe.throw(
				_("Error code {0} is a safety control: it cannot be turned off or changed.").format(
					rule.error_code
				)
			)
		roles = [line.strip() for line in (rule.approver_roles or "").split("\n") if line.strip()]
		for role in roles:
			if not frappe.db.exists("Role", role):
				frappe.throw(_("Role {0} does not exist.").format(role))
		rule.approver_roles = "\n".join(roles)


def record(
	error_code,
	object_type=None,
	object_name=None,
	*,
	station=None,
	client_ts=None,
	block_code=None,
	status=OPEN,
	user=None,
	detail=None,
) -> str:
	"""Ghi một lần phát sinh vào Nhật ký lỗi; trả tên bản ghi."""
	if station and not frappe.db.exists("Zone Station", station):
		station = None
	doc = frappe.get_doc(
		{
			"doctype": LOG_DOCTYPE,
			"error_code": error_code,
			"block_code": block_code,
			"object_type": object_type,
			"object_name": str(object_name)[:140] if object_name else None,
			"station": station,
			"user": user or frappe.session.user,
			"occurred_at": now_datetime(),
			"client_ts": client_time.to_system_time(client_ts) if client_ts else None,
			"status": status,
			"detail": detail,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def record_block(block, station=None, client_ts=None) -> str | None:
	"""Ghi Nhật ký cho một `Block` đã gán mã; mã đang tắt và lỗi nhập liệu không ghi."""
	code = error_code_of(block.code, block.error_code)
	if not code:
		return None
	rule = rule_of(code)
	if not rule or not rule["enabled"]:
		return None
	return record(
		code,
		block.object_type,
		block.object_name,
		station=station if isinstance(station, str) else None,
		client_ts=client_ts,
		block_code=block.code,
		detail="\n".join(item for item in block.items or [] if isinstance(item, str)) or None,
	)


def log_block(block, station=None, client_ts=None) -> None:
	"""Ghi Nhật ký nhưng không bao giờ che mất lời từ chối: lỗi ghi log vào Error Log của Frappe."""
	try:
		record_block(block, station, client_ts)
	except Exception:
		frappe.log_error(title="TraceCore Error Log")


def mark_resolved(error_code, object_type, object_name) -> int:
	"""Đóng các dòng Đang mở của đối tượng khi điều kiện đã hết (cách gỡ Tự hết); trả số dòng đóng."""
	names = frappe.get_all(
		LOG_DOCTYPE,
		filters={
			"error_code": error_code,
			"object_type": object_type,
			"object_name": object_name,
			"status": OPEN,
		},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value(LOG_DOCTYPE, name, "status", RESOLVED, update_modified=False)
	return len(names)


# --- mức độ cấu hình được (FR-M9-18) ------------------------------------------------------------------------


def is_blocking(code: str) -> bool:
	rule = rule_of(code)
	return not rule or (rule["enabled"] and rule["severity"] == BLOCK)


def check(block, station=None):
	"""Áp cấu hình viện lên một `Block`: Chặn trả lại `block`; Cảnh báo/Thông tin ghi Nhật ký, gom vào `warnings`, trả None; mã tắt trả None."""
	code = error_code_of(block.code, block.error_code)
	rule = rule_of(code) if code else None
	if not rule:
		return block
	if not rule["enabled"]:
		return None
	if rule["severity"] == BLOCK:
		return block
	station = station or _current_station()
	if not _warned_today(code, block.object_name):
		log_block(block, station)
	frappe.flags.setdefault("tc_error_warnings", []).append(block.as_dict())
	return None


def _current_station():
	session = frappe.flags.get("tc_station_session")
	return frappe.db.get_value("Station Session", session, "station") if session else None


def _warned_today(code, object_name) -> bool:
	"""Một cảnh báo chỉ ghi một dòng mỗi ngày cho mỗi đối tượng: kiểm tra máy chạy ở từng lần quét, không phải từng lần phát sinh."""
	if not object_name:
		return False
	return bool(
		frappe.db.exists(
			LOG_DOCTYPE,
			{
				"error_code": code,
				"object_name": object_name,
				"status": OPEN,
				"occurred_at": [">=", getdate(now_datetime())],
			},
		)
	)


def pop_warnings() -> list:
	return frappe.flags.pop("tc_error_warnings", None) or []


def attach_warnings(result):
	"""Đưa cảnh báo đã gom vào body RPC; thao tác vẫn thành công."""
	warnings = pop_warnings()
	if warnings and isinstance(result, dict):
		result["warnings"] = warnings
	return result


# --- cho phép tạm (FR-M4-03.1, A-71 e) ----------------------------------------------------------------------

PERMIT_CODES = ("NS-001",)
MAX_PERMIT_HOURS = 24


def _permit_error(reason):
	from tracecore.core.errors import Block, BlockedError

	return BlockedError(
		Block(
			"PERMIT_INVALID",
			_("Temporary access is not valid"),
			reason,
			_("Correct the request, then approve again."),
		)
	)


def _employee_user(employee):
	return frappe.db.get_value("Employee", employee, "user_id")


def _require_approver(row):
	from tracecore.core.errors import Block, BlockedError

	allowed = set((rule_of(row.error_code) or {}).get("approver_roles") or [])
	if not allowed & set(frappe.get_roles()):
		raise BlockedError(
			Block(
				"APPROVER_NOT_ALLOWED",
				_("Not allowed to approve"),
				_("Your role cannot approve temporary access for {0}.").format(row.error_code),
				_("Ask a person with an approver role."),
			)
		)
	if row.object_type == "Employee" and _employee_user(row.object_name) == frappe.session.user:
		raise BlockedError(
			Block(
				"SELF_APPROVAL_NOT_ALLOWED",
				_("You cannot approve your own access"),
				_("This request is for your own account."),
				_("Ask another approver."),
			)
		)


def grant_permit(error_log, hours, reason, client_ts=None) -> dict:
	"""Duyệt cho phép tạm từ một dòng Nhật ký Đang mở: tối đa 24 giờ, có lý do, ghi người duyệt và Audit `Override`."""
	from tracecore.core import audit

	row = frappe.db.get_value(
		LOG_DOCTYPE, error_log, ["name", "error_code", "object_type", "object_name", "status"], as_dict=True
	)
	if not row or row.error_code not in PERMIT_CODES or row.status != OPEN:
		raise _permit_error(_("Only an open certificate error can get temporary access."))
	text = reason.strip() if isinstance(reason, str) else ""
	if not text:
		raise _permit_error(_("A reason is required."))
	value = str(hours).strip()
	if not value.isdigit() or not 1 <= int(value) <= MAX_PERMIT_HOURS:
		raise _permit_error(_("Enter the number of hours, from 1 to {0}.").format(MAX_PERMIT_HOURS))
	_require_approver(row)
	until = add_to_date(now_datetime(), hours=int(value))
	frappe.db.set_value(
		LOG_DOCTYPE,
		row.name,
		{
			"status": ALLOWED,
			"approved_by": frappe.session.user,
			"valid_until": until,
			"approval_reason": text,
		},
	)
	audit.log(
		"Override",
		LOG_DOCTYPE,
		row.name,
		new={"event": "TemporaryAccess", "employee": row.object_name, "hours": int(value), "reason": text},
		reason="TemporaryAccess",
		client_ts=client_ts,
	)
	return {"error_log": row.name, "status": ALLOWED, "valid_until": until}


def active_permit(error_code, object_type, object_name, station=None, needed=()) -> dict | None:
	"""Cho phép tạm còn hiệu lực, đúng trạm được duyệt và phủ đủ `needed` (loại chứng chỉ đang thiếu)."""
	filters = {
		"error_code": error_code,
		"object_type": object_type,
		"object_name": object_name,
		"status": ALLOWED,
		"valid_until": [">", now_datetime()],
	}
	if station:
		filters["station"] = station
	rows = frappe.get_all(
		LOG_DOCTYPE,
		filters=filters,
		fields=["name", "valid_until", "approved_by", "detail"],
		order_by="valid_until desc",
	)
	for row in rows:
		if set(needed) <= set((row.detail or "").split("\n")):
			return row
	return None


def allow_open(error_codes_list, object_type, object_name, until, reason) -> int:
	"""R02 mở khóa tạm máy (`unlock_temp`): các dòng Đang mở của máy thành Được phép tạm, ghi người duyệt và thời hạn."""
	names = frappe.get_all(
		LOG_DOCTYPE,
		filters={
			"error_code": ["in", error_codes_list],
			"object_type": object_type,
			"object_name": object_name,
			"status": OPEN,
		},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value(
			LOG_DOCTYPE,
			name,
			{
				"status": ALLOWED,
				"approved_by": frappe.session.user,
				"valid_until": until,
				"approval_reason": reason,
			},
		)
	return len(names)
