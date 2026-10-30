"""RPC tracecore.v1.par.override.* — đề nghị, duyệt, từ chối ghi đè cơ số (FEAT-032, UC-31, WF-08).

- ``request``: từ trạm T4 (SCR-08), phiên trạm + ``@idempotent``; lỗi nghiệp vụ thành body ``ok: false`` qua ``run_at_step``.
- ``request_desk``, ``approve``, ``reject``: từ Desk (SCR-31); người duyệt nhập PIN. Lỗi nghiệp vụ trả ``ok: false``
  (không ném) để Audit Log ``Reject``, lần PIN sai và bộ đếm khóa PIN được lưu.
"""

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.par import override as service
from tracecore.reprocessing import packing
from tracecore.v1._common import reject_block, require_any_role, run_at_step, station_session

STEP = packing.STEP  # đề nghị từ màn đóng gói T4
REQUEST_ROLES = ("TC R04", "TC R02", "System Manager")
DESK_REQUEST_ROLES = ("TC R01", "TC R02", "TC R04", "System Manager")
DECIDE_ROLES = ("TC R01", "TC R02")  # R02 chỉ khi được ủy quyền (service.is_approver)
SUMMARY_FIELDS = (
	"name",
	"status",
	"set_unit",
	"reason",
	"requested_by",
	"requested_at",
	"extra_cycles",
	"valid_until",
	"decision_reason",
	"decided_by",
	"decided_at",
)


def _summary(doc):
	return {key: (str(doc.get(key)) if doc.get(key) is not None else None) for key in SUMMARY_FIELDS}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*REQUEST_ROLES)
@idempotent
def request(set_id, reason, station, client_ts=None, token=None):
	"""R04 đề nghị ghi đè cho bộ `set_id` (Set ID GIAI) đã hết cơ số; trả ``{"ok": true, "override": {...}}``.

	Lý do trống → ``REASON_REQUIRED``; bộ chưa hết cơ số → ``PAR_NOT_EXCEEDED``; đã có đề nghị chờ hoặc ghi đè hiệu lực
	→ ``OVERRIDE_PENDING``. R01 (và R02 được ủy quyền) nhận thông báo trên Desk.
	"""
	require_any_role(*REQUEST_ROLES)
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(set_id)
	is_set = scanned["type"] == "set"

	def call():
		if not is_set:
			raise BlockedError(
				Block(
					"SCAN_INVALID",
					_("Not a set code"),
					_("Code {0} is not a Set ID.").format(scanned["raw"] or "-"),
					_("Scan the Set ID on the set tag."),
				)
			)
		return {"ok": True, "override": _summary(service.request(scanned["id"], reason, station))}

	return run_at_step(
		STEP,
		station,
		timestamp,
		call,
		"Set Unit" if is_set else None,
		scanned["id"] if is_set else None,
		scanned["raw"],
	)


def _desk(roles, ref_name, call):
	"""Chạy `call()` cho người dùng Desk có một trong `roles`; từ chối nghiệp vụ thành body ``ok: false``."""
	require_any_role(*roles)
	try:
		return {"ok": True, "override": _summary(call())}
	except BlockedError as error:
		return reject_block(error.block, service.DOCTYPE, ref_name)


@frappe.whitelist(methods=["POST"])
def request_desk(set_unit, reason):
	"""Đề nghị ghi đè từ Desk (R01, R02, R04): cùng luật với ``request``."""
	return _desk(DESK_REQUEST_ROLES, set_unit, lambda: service.request(set_unit, reason))


@frappe.whitelist(methods=["POST"])
def approve(override, extra_cycles, valid_until, reason, pin):
	"""R01 (hoặc R02 được ủy quyền) duyệt: số chu trình thêm, thời hạn (ISO), lý do và PIN (SCR-31)."""
	return _desk(
		DECIDE_ROLES, override, lambda: service.approve(override, extra_cycles, valid_until, reason, pin)
	)


@frappe.whitelist(methods=["POST"])
def reject(override, reason, pin):
	"""Từ chối đề nghị: lý do và PIN bắt buộc; bộ giữ Hết vòng đời."""
	return _desk(DECIDE_ROLES, override, lambda: service.reject(override, reason, pin))
