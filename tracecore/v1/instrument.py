"""RPC tracecore.v1.instrument.*: ảnh dụng cụ cho trạm/PDA (FR-M1-01.6, FEAT-014 A-06 I12), xem trước mã GIAI
khắc laser cho đơn vị khắc (FR-M1-02, A-06 I8) và dữ liệu cho form Desk SCR-01 (check_code, form_context).

Chỉ đọc, không `@idempotent`. Dụng cụ không có → `INSTRUMENT_NOT_FOUND` (404) qua `reject_block` (Audit Log `Reject`).
"""

import base64

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, get_fullname

from tracecore.core import code_registry, gs1
from tracecore.core.errors import Block
from tracecore.instrument import catalog, maintenance, media, thresholds, versions
from tracecore.v1._common import reject_block
from tracecore.v1.instrument_admin import ADMIN_ROLES, GIAI_ROLES


@frappe.whitelist(methods=["GET"])
def get_image(instrument=None):
	"""URL ảnh gốc, thumbnail và ``etag`` của dụng cụ (Service Worker cache theo etag, FEAT-009).

	Trả ``{"ok": True, instrument, image_url, thumbnail_url, etag, has_image}``; chưa có ảnh → ``has_image = False``.
	"""
	# kiểm quyền trước mọi thao tác ghi (Audit Log Reject)
	frappe.has_permission("Instrument", "read", throw=True)
	code = instrument.strip()[: gs1.MAX_SCAN_LENGTH] if isinstance(instrument, str) else ""
	if not code or not frappe.db.exists("Instrument", code):
		return reject_block(
			Block(
				"INSTRUMENT_NOT_FOUND",
				_("Instrument not found"),
				_("Instrument {0} does not exist in TraceCore.").format(code or "-"),
				_("Check the instrument code or call R02."),
			),
			"Instrument",
			code or None,
			raw=code or None,
		)
	return {"ok": True, **media.image_info(code)}


def _code_disabled_block(code):
	return Block(
		"CODE_DISABLED",
		_("Code disabled"),
		_("GIAI code {0} is disabled because the instrument is retired.").format(code),
		_("Do not etch this code. A retired instrument cannot be returned to use."),
	)


@frappe.whitelist(methods=["GET"])
def giai_preview(instrument=None):
	"""Ảnh DataMatrix GS1 (AI 8004) của mã GIAI đã cấp, để đơn vị khắc laser đối chiếu trước khi khắc.

	Trả ``{"ok": True, instrument, giai, png_b64, hri, payload}`` (``payload`` có FNC1 dạng GS). Từ chối:
	``INSTRUMENT_NOT_FOUND`` (404), ``GIAI_NOT_ASSIGNED`` (409), ``CODE_DISABLED`` (409, dụng cụ đã ngừng sử dụng),
	``GS1_PREFIX_NOT_CONFIGURED`` (409, mã mang tiền tố demo trên site không phải dev/test: không được khắc).
	"""
	frappe.has_permission("Instrument", "read", throw=True)
	code = instrument.strip()[: gs1.MAX_SCAN_LENGTH] if isinstance(instrument, str) else ""
	giai = frappe.db.get_value("Instrument", code, "giai_code") if code else None
	block = None
	if not code or not frappe.db.exists("Instrument", code):
		block = Block(
			"INSTRUMENT_NOT_FOUND",
			_("Instrument not found"),
			_("Instrument {0} does not exist in TraceCore.").format(code or "-"),
			_("Check the instrument code or call R02."),
		)
	elif not giai:
		block = catalog.not_assigned_block(code)
	elif frappe.db.get_value("Code Registry", giai, "status") != "Active":
		block = _code_disabled_block(giai)
	else:
		block = code_registry.instrument_giai_block(giai)
	if block:
		return reject_block(block, "Instrument", code or None, raw=code or None)
	payload = gs1.giai_payload(giai)
	return {
		"ok": True,
		"instrument": code,
		"giai": giai,
		"png_b64": base64.b64encode(gs1.encode_datamatrix_png(payload)).decode("ascii"),
		"hri": gs1.giai_hri(giai),
		"payload": payload,
	}


# --- Form Desk SCR-01 (FEAT-014 Task 6) ---------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def check_code(code=None):
	"""Kiểm mã dụng cụ khi gõ trên form mới (FR-M1-01.4, UC-01 E1); chỉ đọc, không ghi Audit Log.

	Trả ``{"ok": True, code, valid, available, suggestion}`` sau chuẩn hóa (NFKC, bỏ khoảng trắng, viết hoa); trùng
	(kể cả dụng cụ Ngừng sử dụng) → ``available = False`` + ``suggestion`` = mã kế tiếp còn trống. Sai định dạng →
	``valid = False``, ``code = None`` và ``message`` (quy tắc mã). Lưu bản ghi vẫn kiểm lại ở server.
	"""
	frappe.has_permission("Instrument", "read", throw=True)
	normalized = catalog.clean_code(code)
	if normalized is None:
		return {
			"ok": True,
			"code": None,
			"valid": False,
			"available": False,
			"suggestion": None,
			"message": catalog.code_rule_message(),
		}
	available = not catalog.code_exists(normalized)
	suggestion = None
	if not available:
		try:
			suggestion = catalog.suggest_code(normalized)
		except frappe.ValidationError:
			# hết mã để gợi ý: chỉ báo trùng, không để thông báo của frappe.throw lọt ra
			frappe.clear_last_message()
	return {"ok": True, "code": normalized, "valid": True, "available": available, "suggestion": suggestion}


def _giai_info(row, enabled):
	if not row.giai_code:
		return None
	return {
		"code": row.giai_code,
		"hri": gs1.giai_hri(row.giai_code),
		"etched_on": str(row.giai_etched_on) if row.giai_etched_on else None,
		"position": row.giai_position or None,
		"read_only": not enabled,
	}


def _history(code):
	return [
		{
			"version_no": row["version_no"],
			"methods": row["methods"],
			# giờ hệ thống (Asia/Ho_Chi_Minh); Desk hiện dd/mm/yyyy HH:mm
			"changed_on": get_datetime(row["changed_on"]).strftime("%Y-%m-%d %H:%M:%S"),
			"changed_by": row["changed_by"],
			"changed_by_name": get_fullname(row["changed_by"]) if row["changed_by"] else None,
		}
		for row in versions.history(code)
	]


def _permissions(row, enabled):
	roles = set(frappe.get_roles())
	admin = bool(roles & set(ADMIN_ROLES))
	giai = bool(roles & set(GIAI_ROLES)) and enabled and row.status == "Active"
	return {
		"can_write": bool(frappe.has_permission("Instrument", "write", doc=row.name)),
		"can_retire": admin and row.status == "Active",
		"can_init_counters": admin,
		"can_assign_giai": giai and not row.giai_code,
		"can_record_etching": giai and bool(row.giai_code),
	}


@frappe.whitelist(methods=["GET"])
def form_context(instrument=None):
	"""Dữ liệu cho form Desk SCR-01; chỉ đọc (quyền đọc Instrument), không chép quy tắc nghiệp vụ sang JS.

	Trả ``{"ok": True, instrument, status, version_no, giai_enabled, giai, effective_rule, bom_usage, history, image,
	counters, permissions}``:
	``giai`` None khi chưa có mã, có mã thì ``{code, hri, etched_on, position, read_only}`` (``read_only`` khi cờ tắt);
	``effective_rule`` = ``thresholds.effective_rules`` (``{interval, maint_type, source}`` hoặc None); ``bom_usage`` =
	``catalog.bom_usage``; ``history`` = phiên bản cũ → mới; ``counters`` = ``maintenance.instrument_counters``;
	``permissions`` = nút ghi mà người dùng được thấy (server vẫn kiểm lại ở từng RPC).
	Dụng cụ không có → ``INSTRUMENT_NOT_FOUND`` (404).
	"""
	frappe.has_permission("Instrument", "read", throw=True)
	code = instrument.strip()[: gs1.MAX_SCAN_LENGTH] if isinstance(instrument, str) else ""
	row = (
		frappe.db.get_value(
			"Instrument",
			code,
			["name", "status", "version_no", "giai_code", "giai_etched_on", "giai_position"],
			as_dict=True,
		)
		if code
		else None
	)
	if not row:
		return reject_block(
			Block(
				"INSTRUMENT_NOT_FOUND",
				_("Instrument not found"),
				_("Instrument {0} does not exist in TraceCore.").format(code or "-"),
				_("Check the instrument code or call R02."),
			),
			"Instrument",
			code or None,
			raw=code or None,
		)
	frappe.has_permission("Instrument", "read", doc=row.name, throw=True)
	enabled = catalog.giai_enabled()
	rule = thresholds.effective_rules([row.name]).get(row.name)
	return {
		"ok": True,
		"instrument": row.name,
		"status": row.status,
		"version_no": cint(row.version_no) or 1,
		"giai_enabled": enabled,
		"giai": _giai_info(row, enabled),
		"effective_rule": rule,
		"bom_usage": catalog.bom_usage(row.name),
		"history": _history(row.name),
		"image": media.image_info(row.name),
		"counters": maintenance.instrument_counters(row.name, rule),
		"permissions": _permissions(row, enabled),
	}
