"""RPC tracecore.v1.set_type_admin.*: tạo loại bộ cùng BOM v1, lưu phiên bản BOM mới, sao chép loại bộ (FEAT-015 Task 2).

Quyền TC R02, TC R10, System Manager (S12) và quyền mức bản ghi trên loại bộ có sẵn (ghi khi lưu BOM, đọc nguồn
khi sao chép), kiểm TRƯỚC mọi ghi; mọi RPC là POST + ``@idempotent`` (``X-Idempotency-Key``,
``client_ts`` ISO 8601 có offset). ``header``/``lines`` nhận JSON string hoặc object/list; sai kiểu → ``BadRequestError``
(400). Từ chối nghiệp vụ: body ``{"ok": false, "error"}`` + mã HTTP + Audit Log ``Reject`` (``reject_block``). Thành
công: ``{"ok": true, set_type, bom_version, effective_from, status}``. Nghiệp vụ ở ``tracecore.instrument.bom_versions``.
Sửa hạn lưu loại gói (Task 4, S7): ``set_pack_shelf_life``, nghiệp vụ ở ``tracecore.instrument.shelf_life``.
"""

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.instrument import bom_versions, shelf_life
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

ADMIN_ROLES = ("TC R02", "TC R10", "System Manager")
SET_TYPE = "Instrument Set Type"


def _text(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be text.").format(name))
	return value


def _parsed(value, name, kind):
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except Exception:
			raise BadRequestError(_("{0} must be valid JSON.").format(name)) from None
	if not isinstance(value, kind):
		raise BadRequestError(_("{0} has the wrong type.").format(name))
	return value


def _header(header) -> dict:
	header = _parsed(header, "header", dict)
	unknown = sorted(set(header) - set(bom_versions.HEADER_FIELDS))
	if unknown:
		raise BadRequestError(_("header has fields that cannot be set: {0}.").format(", ".join(unknown)))
	return header


def _lines(lines) -> list:
	lines = _parsed(lines, "lines", list)
	if not all(isinstance(line, dict) for line in lines):
		raise BadRequestError(_("lines must be a list of objects with instrument, qty and position."))
	return lines


def _base_version(value) -> int:
	number = bom_versions.whole_number(value)
	if number is None or number < 0:
		raise BadRequestError(_("base_version must be a whole number of at least 0."))
	return number


def _require_doc_permission(set_type, ptype):
	"""Quyền mức bản ghi (User Permission…) trên loại bộ có sẵn, ngoài role (review cuối Minor 2); loại bộ không có thì
	để nghiệp vụ trả ``SET_TYPE_NOT_FOUND`` (người gọi đã có quyền ghi DocType nên không lộ thêm gì)."""
	name = frappe.db.get_value(SET_TYPE, set_type, "name") if set_type else None
	if name:
		frappe.has_permission(SET_TYPE, ptype, doc=name, throw=True)


def _ref(value):
	return value.strip().upper() if isinstance(value, str) and value.strip() else None


@frappe.whitelist(methods=["POST"])
@idempotent
def create(header, lines, client_ts=None):
	"""Tạo loại bộ cùng BOM phiên bản 1 (FR-M1-03, .1, .3, .6).

	Từ chối: ``BOM_EMPTY``, ``BOM_TOO_LARGE``, ``BOM_LINE_INVALID`` (``items`` lỗi từng dòng) (422),
	``SET_TYPE_CODE_EXISTS`` (409). Lỗi phần đầu (thiếu trường, loại gói/hạn lưu, GTIN) là lỗi kiểm tra của Frappe.
	"""
	require_any_role(*ADMIN_ROLES)
	timestamp = parse_client_ts(client_ts)
	header, lines = _header(header), _lines(lines)
	try:
		name = bom_versions.create_set_type(header, lines)
	except BlockedError as error:
		return reject_block(error.block, SET_TYPE, _ref(header.get("type_code")), client_ts=timestamp)
	return {
		"ok": True,
		"set_type": name,
		"bom_version": 1,
		"effective_from": str(bom_versions.today()),
		"status": bom_versions.STATUS_EFFECTIVE,
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def save_bom(set_type, lines, effective_from, reason, base_version, client_ts=None):
	"""Lưu phiên bản BOM mới từ phiên bản `base_version` người dùng đang xem (FR-M1-04, .4; S4).

	Từ chối: ``SET_TYPE_NOT_FOUND`` (404), ``BOM_VERSION_CONFLICT`` (409, ``items = [{latest}]``: tải lại),
	``REASON_REQUIRED``, ``BOM_EFFECTIVE_DATE_INVALID``, ``BOM_EMPTY``, ``BOM_TOO_LARGE``, ``BOM_LINE_INVALID`` (422).
	"""
	require_any_role(*ADMIN_ROLES)
	timestamp = parse_client_ts(client_ts)
	set_type = _text(set_type, "set_type")
	effective_from = _text(effective_from, "effective_from")
	reason = _text(reason, "reason")
	lines, base = _lines(lines), _base_version(base_version)
	_require_doc_permission(set_type, "write")
	try:
		result = bom_versions.create_version(set_type, lines, effective_from, reason, base)
	except BlockedError as error:
		return reject_block(error.block, SET_TYPE, set_type, client_ts=timestamp)
	return {"ok": True, **result}


@frappe.whitelist(methods=["POST"])
@idempotent
def copy(source, type_code, set_type_name, client_ts=None):
	"""Sao chép loại bộ (UC-02 A2): phần đầu trừ mã/GTIN/ảnh, BOM hiệu lực của nguồn thành v1 của loại bộ mới.

	Từ chối: ``SET_TYPE_NOT_FOUND`` (404), ``SET_TYPE_CODE_EXISTS`` (409), ``BOM_EMPTY``, ``BOM_LINE_INVALID`` (422).
	"""
	require_any_role(*ADMIN_ROLES)
	timestamp = parse_client_ts(client_ts)
	source = _text(source, "source")
	type_code = _text(type_code, "type_code")
	set_type_name = _text(set_type_name, "set_type_name")
	_require_doc_permission(source, "read")
	try:
		name = bom_versions.copy_set_type(source, type_code, set_type_name)
	except BlockedError as error:
		return reject_block(error.block, SET_TYPE, source, client_ts=timestamp)
	return {
		"ok": True,
		"set_type": name,
		"bom_version": 1,
		"effective_from": str(bom_versions.today()),
		"status": bom_versions.STATUS_EFFECTIVE,
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def set_pack_shelf_life(item, days, reason, client_ts=None):
	"""Sửa hạn lưu (ngày) của loại gói kèm lý do; chỉ áp cho gói đóng sau (FR-M2-07.8, BRU-REP-009; S7).

	Từ chối (422): ``PACK_TYPE_INVALID`` (Item không phải Packaging), ``SHELF_LIFE_INVALID`` (không phải số nguyên
	1-3650), ``REASON_REQUIRED``. Thành công: ``{"ok": true, item, old_days, new_days, affected_set_types}``
	(``affected_set_types`` = loại bộ có ghi đè thành vô hiệu theo ``min``: cảnh báo, không chặn).
	"""
	require_any_role(*ADMIN_ROLES)
	timestamp = parse_client_ts(client_ts)
	item = _text(item, "item")
	reason = _text(reason, "reason")
	try:
		result = shelf_life.set_pack_shelf_life(item, days, reason)
	except BlockedError as error:
		ref = item.strip() if item and item.strip() else None
		return reject_block(error.block, shelf_life.ITEM, ref, client_ts=timestamp)
	return {"ok": True, **result}
