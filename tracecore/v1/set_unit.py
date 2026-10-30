"""RPC tracecore.v1.set_unit.*: tra cứu, cấp Set ID hàng loạt, in thẻ kim loại / nhãn khay (FEAT-016; FR-M1-05, .1,
.3, .4; BRU-ID-001, BRU-ID-006; UC-03; A-09 G1, G3, G7, G9, G10, G12, G16).

- Ghi (POST + ``@idempotent``): `create_batch`, `print_tags`, `reprint_tag`, `cancel_print`, `verify_tag`. Role kiểm
  TRƯỚC mọi ghi, nên user thiếu quyền không để lại Idempotency Key/Audit (G7): cấp, in, in lại, hủy lệnh in kẹt —
  ``ISSUE_ROLES``; quét kiểm tra thẻ thêm TC R04 (``VERIFY_ROLES``).
- Vòng đời (Task 6, hiện thực ở `set_unit_lifecycle`): `form_context`, `history` (GET).
- Đọc (GET): `tag_preview`, `print_status`, `batch_csv`. Từ chối và dòng Audit xuất CSV qua `keep_writes_on_get` để
  được commit (Frappe v15 không commit request GET).
- Tham số sai kiểu → `BadRequestError` (400); từ chối nghiệp vụ → `reject_block` (Audit ``Reject`` + 404/409/422).
  Mọi ngữ cảnh nhãn dựng qua `set_tags.tag_context` (chặn tiền tố demo, G3).
"""

import csv
import io

import frappe
from frappe import _
from frappe.utils import now_datetime

from tracecore.core import audit, gs1
from tracecore.core import print as core_print
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.instrument import set_tags, set_units
from tracecore.setup.label_templates import sample_set_context
from tracecore.v1._common import (
	BadRequestError,
	desk_printer,
	job_names,
	keep_writes_on_get,
	reject_block,
	rejection,
	require_any_role,
)

# Task 6: vòng đời (ngữ cảnh form, lịch sử) ở module riêng, công bố lại ở đây để giữ đường RPC
# tracecore.v1.set_unit.<action> của plan; role cấp/in/quét kiểm tra dùng chung đặt ở đó
from tracecore.v1.set_unit_disposal import (  # RPC công bố lại (FEAT-004 thanh lý)
	disposal_approve,
	disposal_reject,
	disposal_request,
)
from tracecore.v1.set_unit_lifecycle import (  # RPC công bố lại
	ISSUE_ROLES,
	VERIFY_ROLES,
	form_context,
	history,
)

MAX_STATUS_JOBS = 200  # 100 bộ, mỗi bộ 2 loại bản in
MAX_NUMBER_CHARS = (
	6  # số lượng / cơ số / số chu trình gửi dạng chuỗi: dài hơn thì chắc chắn ngoài khoảng, không int()
)
MAX_NAME_CHARS = 140
SAVEPOINT = "tc_create_set_batch"
EXPORT_REASON = "export"
CSV_COLUMNS = ("set_id", "hri", "element_string", "set_type", "set_type_name", "department")
# Ô CSV mở bằng Excel/LibreOffice bắt đầu bằng các ký tự này bị hiểu là công thức (CSV injection, OWASP)
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

FIELDS = (
	"name",
	"set_type",
	"status",
	"cycles_used",
	"max_cycles",
	"active_cycle_id",
	"current_station",
	"is_loaner",
	"department",
)


def _reject(code, title, reason, action, raw):
	audit.log("Reject", reason=code, new={"raw": raw})
	return rejection(code, title, reason, action)


@frappe.whitelist(methods=["POST"])
@idempotent
def get(set_id, client_ts=None):
	"""Tra cứu Set Unit theo chuỗi quét (Set ID GIAI); mã lạ → từ chối và ghi Audit Log (FR-M9-07.3)."""
	# kiểm quyền trước mọi thao tác ghi (Audit Log Reject) — user không có quyền không để lại dấu vết
	frappe.has_permission("Set Unit", "read", throw=True)
	scanned = gs1.parse_scan(set_id)
	if scanned["type"] == "unknown":
		return _reject(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} was not issued by TraceCore.").format(scanned["raw"]),
			_("Rescan the set tag or call R02."),
			scanned["raw"],
		)
	if scanned["type"] != "set":
		return _reject(
			"SCAN_WRONG_TYPE",
			_("Not a set code"),
			_("Code {0} is not a Set ID.").format(scanned["id"]),
			_("Scan the Set ID on the set tag."),
			scanned["raw"],
		)

	row = frappe.db.get_value("Set Unit", scanned["id"], FIELDS, as_dict=True)
	if not row:
		return _reject(
			"SET_NOT_FOUND",
			_("Set not found"),
			_("Set ID {0} does not exist in TraceCore.").format(scanned["id"]),
			_("Check the set tag or call R02."),
			scanned["raw"],
		)
	frappe.has_permission("Set Unit", "read", doc=row.name, throw=True)

	set_type = frappe.db.get_value(
		"Instrument Set Type", row.set_type, ["set_type_name", "method"], as_dict=True
	)
	data = {key: row[key] for key in FIELDS if key != "name"}
	data.update(
		set_id=row.name,
		set_type_name=set_type.set_type_name if set_type else None,
		method=set_type.method if set_type else None,
	)
	return {"ok": True, "set_unit": data}


# --- Tham số ----------------------------------------------------------------------------------------------------------


def _text(value, field):
	"""Chuỗi bắt buộc (tên loại bộ, Set ID…); thiếu, rỗng, sai kiểu hoặc quá dài → 400."""
	if not isinstance(value, str) or not value.strip() or len(value) > MAX_NAME_CHARS:
		raise BadRequestError(_("{0} must be a non-empty text.").format(field))
	return value.strip()


def _optional_text(value, field):
	if value is None or value == "":
		return None
	return _text(value, field)


def _whole_arg(value, field, too_long):
	"""Số nguyên dạng int hoặc chuỗi (hộp thoại Desk). Kiểu khác (bool, số thực, list…) → 400.

	Chuỗi dài hơn `MAX_NUMBER_CHARS` ký tự chắc chắn ngoài khoảng: trả `too_long` để tầng nghiệp vụ từ chối đúng mã,
	không đưa chuỗi khổng lồ vào ``int()`` (Python giới hạn 4300 chữ số → lỗi 500).
	"""
	if isinstance(value, bool) or not isinstance(value, int | str):
		raise BadRequestError(_("{0} must be a whole number.").format(field))
	if isinstance(value, str) and len(value.strip()) > MAX_NUMBER_CHARS:
		return too_long
	return value


def _optional_whole_arg(value, field):
	if value is None or value == "":
		return value
	return _whole_arg(value, field, -1)


def _json_list(value, field):
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value) if value.strip() else []
		except ValueError:
			raise BadRequestError(_("{0} must be a list.").format(field)) from None
	if value is None:
		value = []
	if not isinstance(value, list):
		raise BadRequestError(_("{0} must be a list.").format(field))
	return value


def _kind(value):
	if not isinstance(value, str) or value not in set_tags.KINDS:
		raise BadRequestError(_("kind must be one of {0}.").format(", ".join(set_tags.KINDS)))
	return value


def _kinds(value, required=False):
	"""Loại bản in ⊂ {tag, tray} (list hoặc chuỗi JSON), thứ tự cố định thẻ rồi nhãn khay; sai → 400."""
	kinds = [_kind(kind) for kind in _json_list(value, "kinds")]
	if required and not kinds:
		raise BadRequestError(_("Choose at least one label kind to print."))
	return [kind for kind in set_tags.KINDS if kind in kinds]


def _units(value):
	"""1-`set_tags.MAX_UNITS` Set ID khác nhau (list hoặc chuỗi JSON), giữ thứ tự; sai → 400."""
	units = _json_list(value, "set_units")
	if not units or not all(isinstance(unit, str) and unit and len(unit) <= MAX_NAME_CHARS for unit in units):
		raise BadRequestError(_("set_units must be a non-empty list of Set IDs."))
	units = list(dict.fromkeys(units))
	if len(units) > set_tags.MAX_UNITS:
		raise BadRequestError(_("At most {0} sets can be printed at once.").format(set_tags.MAX_UNITS))
	return units


def _printers(kinds, tag_printer, tray_printer):
	"""``{kind: Printer}`` đang hoạt động cho mỗi loại đã chọn; thiếu/không hoạt động → 400."""
	chosen = {"tag": tag_printer, "tray": tray_printer}
	return {kind: desk_printer(chosen[kind]) for kind in kinds}


def _reason_required():
	return Block(
		"REASON_REQUIRED",
		_("Reason is required"),
		_("A reason of 1 to {0} characters is required.").format(set_tags.REASON_MAX),
		_("Enter why the tag is printed again, at most {0} characters.").format(set_tags.REASON_MAX),
	)


def _render_failed(error, kind):
	return Block(
		"LABEL_RENDER_FAILED",
		_("Label could not be rendered"),
		str(error),
		_("Ask R10 to check the active label template for this object."),
		items=[{"kind": kind}],
	)


def _trial_render(kind, printer):
	"""Dựng thử mẫu active của `kind` bằng ngữ cảnh mẫu (G9) trước khi cấp: mẫu thiếu/lỗi → ``LABEL_RENDER_FAILED``."""
	label = set_tags.KINDS[kind]
	logged = len(frappe.local.message_log)
	try:
		core_print.render_label(label, sample_set_context(label), printer)
	except frappe.ValidationError as error:
		del frappe.local.message_log[logged:]
		raise BlockedError(_render_failed(error, kind)) from None


def _block_unit(block, default):
	"""Set Unit mà từ chối nói tới (mục đầu tiên có ``set_unit``), không có thì `default`."""
	for item in block.items or []:
		if isinstance(item, dict) and item.get("set_unit"):
			return item["set_unit"]
	return default


# --- Cấp và in --------------------------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
@idempotent
def create_batch(
	set_type,
	count,
	department=None,
	max_cycles=None,
	origin="New",
	cycles_used=0,
	estimate_reason=None,
	kinds=None,
	tag_printer=None,
	tray_printer=None,
	client_ts=None,
):
	"""Cấp `count` Set ID cho loại bộ `set_type` và (tùy chọn) xếp hàng in thẻ/nhãn khay trong cùng transaction.

	`kinds` ⊂ {``tag``, ``tray``} (rỗng → chỉ cấp); mỗi loại cần máy in (`tag_printer`/`tray_printer`) đang hoạt
	động có địa chỉ mạng. Thứ tự kiểm (trước mọi ghi): role → tham số (400) → ``PRINTER_NOT_NETWORK`` →
	``COUNT_OUT_OF_RANGE`` → điều kiện cấp (`set_units.precheck`) → dựng thử mẫu (``LABEL_RENDER_FAILED``). Rồi
	`set_units.issue_batch` + `set_tags.queue_prints` trong một savepoint: lỗi ở bước in → không còn Set ID nào.
	Trả ``{"ok": true, "set_type", "set_ids", "jobs", "warnings"}``; replay cùng key → cùng Set ID (G1).
	"""
	require_any_role(*ISSUE_ROLES)
	timestamp = parse_client_ts(client_ts)
	set_type = _text(set_type, "set_type")
	count = _whole_arg(count, "count", 0)
	department = _optional_text(department, "department")
	max_cycles = _optional_whole_arg(max_cycles, "max_cycles")
	cycles_used = _optional_whole_arg(cycles_used, "cycles_used")
	if estimate_reason is not None and not isinstance(estimate_reason, str):
		raise BadRequestError(_("{0} must be a non-empty text.").format("estimate_reason"))
	if not isinstance(origin, str) or origin not in set_units.ORIGINS:
		raise BadRequestError(_("Set origin must be one of: {0}.").format(", ".join(set_units.ORIGINS)))
	kinds = _kinds(kinds)
	printers = _printers(kinds, tag_printer, tray_printer)
	try:
		block = set_tags.printer_block([printers[kind].name for kind in kinds])
		if block:
			raise BlockedError(block)
		if set_units.parse_count(count) is None:
			raise BlockedError(set_units.count_block())
		ctx = set_units.precheck(set_type, department, max_cycles, origin, cycles_used, estimate_reason)
		for kind in kinds:
			_trial_render(kind, printers[kind])
		frappe.db.savepoint(SAVEPOINT)
		try:
			set_ids = set_units.issue_batch(
				set_type, count, department, max_cycles, origin, cycles_used, estimate_reason
			)
			printed = (
				set_tags.queue_prints(set_ids, kinds, {kind: printers[kind].name for kind in kinds})
				if kinds
				else {"jobs": [], "warnings": []}
			)
		except Exception:
			frappe.db.rollback(save_point=SAVEPOINT)  # cả lô hoặc không gì (G1)
			raise
	except BlockedError as error:
		return reject_block(error.block, "Instrument Set Type", set_type, client_ts=timestamp)
	return {
		"ok": True,
		"set_type": ctx["set_type"],
		"set_ids": set_ids,
		"jobs": printed["jobs"],
		"warnings": ctx["warnings"] + printed["warnings"],
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def print_tags(set_units, kinds, tag_printer=None, tray_printer=None, client_ts=None):
	"""In gốc / in bù thẻ và nhãn khay cho 1-100 bộ (FR-M1-05, .4); trả ``{"ok": true, "jobs", "warnings"}``.

	Bộ đã có bản in ``Printed`` của loại đó cần lý do → ``REASON_REQUIRED`` (422) kèm ``items`` (dùng `reprint_tag`);
	job cùng loại đang chờ → ``TAG_PRINT_PENDING``; bộ thanh lý/mã vô hiệu/tiền tố demo → như `set_tags.check_printable`.
	"""
	require_any_role(*ISSUE_ROLES)
	timestamp = parse_client_ts(client_ts)
	units = _units(set_units)
	kinds = _kinds(kinds, required=True)
	printers = _printers(kinds, tag_printer, tray_printer)
	try:
		result = set_tags.queue_prints(units, kinds, {kind: printers[kind].name for kind in kinds})
	except BlockedError as error:
		return reject_block(error.block, "Set Unit", _block_unit(error.block, units[0]), client_ts=timestamp)
	return {"ok": True, **result}


@frappe.whitelist(methods=["POST"])
@idempotent
def reprint_tag(set_unit, kind, printer, reason, client_ts=None):
	"""In lại thẻ/nhãn khay của một bộ với lý do bắt buộc 1-500 ký tự (FR-M1-05.3, UC-03 A2, G10).

	Trả ``{"ok": true, "print_job", "status", "warning", "counts"}``; ``warning`` = ``TAG_REPRINTED`` từ lần in lại
	thứ 3, ``counts`` = `set_tags.print_counts` sau khi xếp hàng.
	"""
	require_any_role(*ISSUE_ROLES)
	timestamp = parse_client_ts(client_ts)
	set_unit = _text(set_unit, "set_unit")
	kind = _kind(kind)
	row = desk_printer(printer)
	text = reason.strip() if isinstance(reason, str) else ""
	try:
		if not text or len(text) > set_tags.REASON_MAX:
			raise BlockedError(_reason_required())
		result = set_tags.queue_prints([set_unit], [kind], {kind: row.name}, text)
	except BlockedError as error:
		return reject_block(error.block, "Set Unit", set_unit, client_ts=timestamp)
	job = result["jobs"][0]
	return {
		"ok": True,
		"print_job": job["print_job"],
		"status": job["status"],
		"warning": result["warnings"][0] if result["warnings"] else None,
		"counts": set_tags.print_counts(set_unit),
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def cancel_print(set_unit, kind=None, reason=None, client_ts=None):
	"""Hủy lệnh in thẻ/nhãn khay đang chờ bị kẹt của một bộ (ruling Task 4/5), lý do bắt buộc 1-500 ký tự.

	`kind` rỗng → mọi loại. Trả ``{"ok": true, "cancelled": [Print Job], "counts"}``; không có job chờ → danh sách rỗng.
	"""
	require_any_role(*ISSUE_ROLES)
	timestamp = parse_client_ts(client_ts)
	set_unit = _text(set_unit, "set_unit")
	kind = None if kind in (None, "") else _kind(kind)
	try:
		cancelled = set_tags.cancel_pending(set_unit, kind, reason)
	except BlockedError as error:
		return reject_block(error.block, "Set Unit", set_unit, client_ts=timestamp)
	return {"ok": True, "cancelled": cancelled, "counts": set_tags.print_counts(set_unit)}


@frappe.whitelist(methods=["POST"])
@idempotent
def verify_tag(set_unit, raw, client_ts=None):
	"""Quét thẻ vừa in (UC-03 bước 4, E2; G12): đúng Set ID của bộ → ghi ``tag_verified_on/by``.

	Trả ``{"ok": true, "set_unit", "verified_on"}``; Set ID khác → ``TAG_MISMATCH`` (409), mã lạ → ``SCAN_INVALID``,
	bộ không có → ``SET_NOT_FOUND`` (Audit ``Reject`` mang chuỗi quét).
	"""
	require_any_role(*VERIFY_ROLES)
	timestamp = parse_client_ts(client_ts)
	try:
		result = set_tags.verify(set_unit, raw)
	except BlockedError as error:
		return reject_block(
			error.block,
			"Set Unit",
			set_unit if isinstance(set_unit, str) else None,
			raw if isinstance(raw, str) else None,
			client_ts=timestamp,
		)
	return {"ok": True, **result}


# --- Đọc --------------------------------------------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def tag_preview(set_unit, kind):
	"""Xem trước thẻ/nhãn khay của một bộ: ``{"ok": true, "png_b64", "zpl", "hri"}`` (ZPL như máy in không Unicode).

	Bộ không in được (thanh lý, mã vô hiệu, tiền tố demo ngoài dev/test) → cùng từ chối như in.
	"""
	require_any_role(*ISSUE_ROLES)
	frappe.has_permission("Set Unit", "read", throw=True)
	set_unit = _text(set_unit, "set_unit")
	kind = _kind(kind)
	try:
		block = set_tags.check_printable(set_unit)
		if block:
			raise BlockedError(block)
		try:
			data = set_tags.preview(set_unit, kind)
		except BlockedError:
			raise
		except frappe.ValidationError as error:
			raise BlockedError(_render_failed(error, kind)) from None
	except BlockedError as error:
		return reject_block(error.block, "Set Unit", set_unit)
	return {"ok": True, **data}


@frappe.whitelist(methods=["GET"])
def print_status(names):
	"""Kết quả các job thẻ/nhãn khay Desk vừa tạo (chỉ ``ref_doctype = Set Unit``; job khác bị bỏ qua).

	Trả ``{"ok": true, "jobs": {tên: {"status", "attempts", "error", "printed_at", "set_unit", "kind"}}}``.
	"""
	require_any_role(*ISSUE_ROLES)
	names = job_names(names, MAX_STATUS_JOBS)
	rows = frappe.get_all(
		"Print Job",
		filters={"name": ["in", names], "ref_doctype": set_tags.REF_DOCTYPE},
		fields=["name", "status", "attempts", "error", "printed_at", "ref_name", "data"],
	)
	jobs = {}
	for row in rows:
		data = frappe.parse_json(row.data) if row.data else {}
		jobs[str(row.name)] = {
			"status": row.status,
			"attempts": row.attempts or 0,
			"error": row.error or None,
			"printed_at": str(row.printed_at) if row.printed_at else None,
			"set_unit": row.ref_name,
			"kind": data.get("kind") if isinstance(data, dict) else None,
		}
	return {"ok": True, "jobs": jobs}


def _csv_cell(value):
	"""Ô CSV an toàn khi mở bằng bảng tính: bắt đầu bằng ``= + - @``/Tab/CR → thêm dấu nháy đơn (không thành công thức)."""
	text = "" if value is None else str(value)
	return "'" + text if text.startswith(CSV_FORMULA_PREFIXES) else text


@frappe.whitelist(methods=["GET"])
def batch_csv(set_units):
	"""Tải CSV Set ID của 1-100 bộ cho đơn vị khắc laser (G8): UTF-8 có BOM, cột `CSV_COLUMNS`.

	``element_string`` = chuỗi phần tử GS1 dạng ngoặc ``(8004)<GIAI>`` (giống ``hri`` in dưới DataMatrix). Bộ không in
	được (thanh lý, mã vô hiệu, tiền tố demo ngoài dev/test) → từ chối như in, không tạo file. Mỗi lần xuất một Audit
	``Create`` (ref Set Unit đầu, ``new = {count, set_ids}``, lý do ``export``).
	"""
	require_any_role(*ISSUE_ROLES)
	units = _units(set_units)
	rows = []
	for unit in units:
		try:
			block = set_tags.check_printable(unit)
			if block:
				raise BlockedError(block)
			ctx = set_tags.tag_context(unit, "tag")
		except BlockedError as error:
			return reject_block(error.block, "Set Unit", unit)
		set_type = frappe.db.get_value(set_tags.REF_DOCTYPE, unit, "set_type")
		element_string = gs1.giai_hri(ctx["set_id"])
		rows.append(
			(ctx["set_id"], ctx["hri"], element_string, set_type, ctx["set_type_name"], ctx["department"])
		)
	buffer = io.StringIO()
	writer = csv.writer(buffer, lineterminator="\r\n")
	writer.writerow(CSV_COLUMNS)
	writer.writerows([[_csv_cell(value) for value in row] for row in rows])
	audit.log(
		"Create",
		set_tags.REF_DOCTYPE,
		units[0],
		new={"count": len(units), "set_ids": units},
		reason=EXPORT_REASON,
	)
	keep_writes_on_get()
	response = frappe.local.response
	response.filename = f"set-ids-{now_datetime():%Y%m%d-%H%M}.csv"
	response.filecontent = ("﻿" + buffer.getvalue()).encode("utf-8")
	response.type = "download"
