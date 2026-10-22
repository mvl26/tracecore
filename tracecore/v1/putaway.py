"""RPC tracecore.v1.putaway.* — màn T6 kho vô khuẩn (SCR-11, FEAT-025): quét, tồn, FEFO.

Lớp mỏng trên `tracecore.reprocessing.storage`: kiểm quyền → kiểm định dạng tham số → gọi dịch vụ. Từ chối nghiệp vụ
(`BlockedError`) thành ``{"ok": false, "error": {...}}`` kèm mã HTTP và Audit Log `Reject` (xem `_common.run_at_step`).
Hai RPC ghi (`scan`, `pack.mark_damaged`) dùng ``@idempotent``; `overview`, `fefo` chỉ đọc.
"""

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import storage
from tracecore.v1._common import STORAGE_ROLES, require_any_role, run_at_step

STEP = storage.STEP  # màn kho vô khuẩn chỉ chạy ở trạm bước T6
READ_ROLES = (*STORAGE_ROLES, "TC R02")


def _route(scanned, raw, station, open_pack, client_ts):
	"""Ô quét duy nhất của màn T6: Cycle ID mở thẻ gói; mã kệ `KE-` sau khi đã mở gói thì nhập kho/chuyển vị trí."""
	kind = scanned["type"]
	if kind == "pack":
		return {"ok": True, "kind": "pack", "pack": storage.pack_card(raw)}
	if kind == "location" and open_pack:
		return {
			"ok": True,
			"kind": "stored",
			"stored": storage.putaway(open_pack, raw, station, client_ts),
		}
	if kind == "location":
		reason = _("Shelf {0} was scanned before any pack.").format(scanned["id"])
		action = _("Scan the Cycle ID on the pack label first, then the shelf.")
	else:
		reason = _("Code {0} is not a pack label or a shelf code.").format(scanned["raw"] or "-")
		action = _("Scan the DataMatrix or Cycle ID on the pack, then the KE- code on the shelf.")
	raise BlockedError(Block("SCAN_INVALID", _("Invalid code"), reason, action))


@frappe.whitelist(methods=["POST"])
@idempotent
def scan(raw, station, open_pack=None, client_ts=None):
	"""Xử lý một lần quét ở màn T6. Trả ``{"ok": true, "kind": ..., <kind>: ...}``:

	- ``pack`` (Cycle ID hoặc DataMatrix nhãn): thẻ gói kèm năm cổng của bộ;
	- ``stored`` (mã kệ ``KE-####`` khi `open_pack` là gói đang mở): gói vào kho hoặc đổi kệ.

	Từ chối nghiệp vụ: xem `_common.run_at_step` (404 kệ/gói không có, 409 gói chưa giải phóng/quá hạn/thiếu cổng,
	422 mã không dùng được).
	"""
	require_any_role(*STORAGE_ROLES)
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(raw)
	ref = {"pack": "Pack", "location": "Sterile Location"}.get(scanned["type"])
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: _route(scanned, raw, station, open_pack, timestamp),
		ref,
		scanned["id"] if ref else None,
		scanned["raw"],
	)


@frappe.whitelist()
def overview(station=None):
	"""Dashboard kho (FR-M2-13.2): tồn theo loại bộ và vị trí, gói hết hạn trong 7 ngày, danh sách gói về khu bẩn."""
	require_any_role(*READ_ROLES)
	return {"ok": True, **storage.overview(), "return_list": storage.return_list()}


@frappe.whitelist()
def fefo(set_type, cycle_id=None):
	"""Gợi ý FEFO cho loại bộ (FR-M2-13.3) và cảnh báo nếu `cycle_id` được chọn có hạn xa hơn gói còn lại (.4)."""
	require_any_role(*READ_ROLES)
	return {
		"ok": True,
		"suggested": storage.fefo_suggest(set_type),
		"warning": storage.fefo_check(cycle_id) if cycle_id else None,
	}
