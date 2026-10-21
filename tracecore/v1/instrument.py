"""RPC tracecore.v1.instrument.*: ảnh dụng cụ cho trạm/PDA (FR-M1-01.6, FEAT-014 A-06 I12).

Chỉ đọc, không `@idempotent`. Dụng cụ không có → `INSTRUMENT_NOT_FOUND` (404) qua `reject_block` (Audit Log `Reject`).
"""

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core.errors import Block
from tracecore.instrument import media
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
