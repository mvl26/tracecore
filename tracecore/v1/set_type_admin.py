"""RPC tracecore.v1.set_type_admin.*: tạo loại bộ cùng BOM v1, lưu phiên bản BOM mới, sao chép loại bộ (FEAT-015 Task 2).

Quyền TC R02, TC R10, System Manager (S12), kiểm TRƯỚC mọi ghi; mọi RPC là POST + ``@idempotent`` (``X-Idempotency-Key``,
``client_ts`` ISO 8601 có offset). ``header``/``lines`` nhận JSON string hoặc object/list; sai kiểu → ``BadRequestError``
(400). Từ chối nghiệp vụ: body ``{"ok": false, "error"}`` + mã HTTP + Audit Log ``Reject`` (``reject_block``). Thành
công: ``{"ok": true, set_type, bom_version, effective_from, status}``. Nghiệp vụ ở ``tracecore.instrument.bom_versions``.
"""

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.instrument import bom_versions
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
