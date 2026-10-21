"""RPC tracecore.v1.instrument.*: ảnh dụng cụ cho trạm/PDA (FR-M1-01.6, FEAT-014 A-06 I12) và xem trước mã GIAI
khắc laser cho đơn vị khắc (FR-M1-02, A-06 I8).

Chỉ đọc, không `@idempotent`. Dụng cụ không có → `INSTRUMENT_NOT_FOUND` (404) qua `reject_block` (Audit Log `Reject`).
"""

import base64

import frappe
from frappe import _

from tracecore.core import code_registry, gs1
from tracecore.core.errors import Block
from tracecore.instrument import catalog, media
from tracecore.v1._common import reject_block


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
		block = code_registry.etching_prefix_block(
			giai[: -len(gs1.INSTRUMENT_ASSET_PREFIX) - gs1.INSTRUMENT_SERIAL_DIGITS]
		)
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
