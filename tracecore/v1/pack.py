"""RPC tracecore.v1.pack.* — màn T4 đóng gói (SCR-08, FEAT-018): quét, sinh Cycle ID, in lại, hủy.

Lớp mỏng trên `tracecore.reprocessing.packing`: kiểm quyền → kiểm định dạng tham số → gọi dịch vụ. Từ chối nghiệp vụ
(`BlockedError`) thành ``{"ok": false, "error": {...}}`` kèm mã HTTP (404/409/422) và Audit Log `Reject`, không ném
lại (xem `_common.run_at_step`). Tham số sai định dạng là 400 (`BadRequestError`); thiếu quyền là 403.
"""

import json

import frappe
from frappe import _
from frappe.utils import today

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.reprocessing import packing
from tracecore.v1._common import (
	PACKING_ROLES,
	BadRequestError,
	require_any_role,
	run_at_step,
	station_session,
)
from tracecore.v1.printer import change_roll

STEP = packing.STEP  # màn đóng gói chỉ chạy ở trạm bước T4
MAINT_KEYS = ("instrument", "action", "oil_batch", "reason")
REF_BY_KIND = {"set": "Set Unit", "pack": "Pack"}


# --- Định dạng tham số (400) -------------------------------------------------------------------------


def _json_list(value, message):
	"""`value` là list hoặc chuỗi JSON của một list (form-encoded gửi list dạng chuỗi); ngược lại 400."""
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			raise BadRequestError(message) from None
	if not isinstance(value, list):
		raise BadRequestError(message)
	return value


def _confirmed_lines(value):
	lines = _json_list(value, _("confirmed_lines must be a list of instrument codes."))
	if not all(isinstance(line, str) for line in lines):
		raise BadRequestError(_("confirmed_lines must be a list of instrument codes."))
	return lines


def _maint_actions(value):
	"""Danh sách xử lý bảo dưỡng: mỗi phần tử có `instrument` và `action` Done/Deferred; chỉ giữ khóa hợp lệ."""
	message = _(
		"maint_actions must be a list of objects with an instrument and an action (Done or Deferred)."
	)
	actions = []
	for item in [] if value is None else _json_list(value, message):
		valid = (
			isinstance(item, dict)
			and isinstance(item.get("instrument"), str)
			and item.get("action") in packing.MAINT_ACTIONS
			and all(item.get(key) is None or isinstance(item[key], str) for key in MAINT_KEYS)
		)
		if not valid:
			raise BadRequestError(message)
		actions.append({key: item[key] for key in MAINT_KEYS if key in item})
	return actions


# --- Quét ----------------------------------------------------------------------------------------------


def _scan_invalid(scanned):
	"""Mã không dùng được ở màn đóng gói: lạ (khi chưa mở bộ) hoặc mã nội bộ của loại khác (nhân viên, thiết bị…)."""
	if scanned["type"] == "unknown":
		reason = _("Code {0} is not a set, pack or label roll.")
		action = _("Scan indicator lots in the separate indicator lot field.")
	else:
		reason = _("Code {0} is not a set, pack or label roll.")
		action = _("Scan the Set ID, the Cycle ID or the label roll code.")
	return BlockedError(
		Block("SCAN_INVALID", _("Invalid code"), reason.format(scanned["raw"] or "-"), action)
	)


def _open_set_method(open_set):
	"""Phương pháp (Steam/Plasma) của bộ đang mở; mã không phải Set ID hoặc không có bộ → SET_NOT_FOUND."""
	scanned = gs1.parse_scan(open_set)
	set_type = (
		frappe.db.get_value("Set Unit", scanned["id"], "set_type") if scanned["type"] == "set" else None
	)
	method = frappe.db.get_value("Instrument Set Type", set_type, "method") if set_type else None
	if not method:
		raise BlockedError(
			Block(
				"SET_NOT_FOUND",
				_("Set not found"),
				_("Set ID {0} does not exist in TraceCore.").format(scanned["raw"] or "-"),
				_("Check the set tag or call R02."),
			)
		)
	return method


def _route(scanned, raw, station, open_set):
	"""Ô chính T4: Set ID, Cycle ID hoặc cuộn nhãn; lô chỉ thị có endpoint riêng."""
	kind = scanned["type"]
	if kind == "set":
		return {"ok": True, "kind": "context", "context": packing.get_context(raw, station)}
	if kind == "pack":
		return {"ok": True, "kind": "pack", "pack": packing.lookup(raw)}
	if kind == "roll":
		return {"ok": True, "kind": "roll", "roll": change_roll(scanned["id"], station)}
	raise _scan_invalid(scanned)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*PACKING_ROLES)
@idempotent
def scan(raw, station, open_set=None, client_ts=None, token=None):
	"""Xử lý một lần quét ở màn T4. Trả ``{"ok": true, "kind": ..., <kind>: ...}``:

	- ``context`` (Set ID): ngữ cảnh đóng gói của bộ (BOM, cổng, bảo dưỡng, cơ số, loại gói, máy in);
	- ``pack`` (Cycle ID hoặc DataMatrix nhãn gói): tra cứu gói (AC-14);
	- ``roll`` (``CN-#####``): đổi cuộn của máy in duy nhất của trạm (AC-9);
	Lô chỉ thị dùng endpoint ``resolve_ci`` của ô riêng, không phân loại từ ô chính.

	Từ chối nghiệp vụ: xem `_common.run_at_step`; mã lạ khi chưa mở bộ và mã loại khác là ``SCAN_INVALID`` (422).
	"""
	require_any_role(*PACKING_ROLES)
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(raw)
	ref_doctype, ref_name = REF_BY_KIND.get(scanned["type"]), scanned["id"]
	if scanned["type"] == "unknown" and open_set:
		ref_doctype, ref_name = "Set Unit", gs1.parse_scan(open_set)["id"]  # từ chối nói về bộ đang mở
	if not (ref_doctype and ref_name):
		ref_doctype = ref_name = None
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: _route(scanned, raw, station, open_set),
		ref_doctype,
		ref_name,
		scanned["raw"],
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*PACKING_ROLES)
@idempotent
def resolve_ci(raw, station, open_set, client_ts=None, token=None):
	"""Ô lô chỉ thị riêng: giữ nguyên kiểm tra loại 5/6, phương pháp và hạn dùng FEAT-018."""
	require_any_role(*PACKING_ROLES)
	if not isinstance(raw, str) or not isinstance(open_set, str):
		raise BadRequestError(_("raw and open_set must be strings."))
	timestamp = parse_client_ts(client_ts)

	def resolve():
		lot = packing.resolve_ci_batch(raw.strip(), _open_set_method(open_set), today())
		return {"ok": True, "kind": "ci", "ci": {**lot, "expiry_date": str(lot["expiry_date"])}}

	scanned = gs1.parse_scan(open_set)
	return run_at_step(
		STEP,
		station,
		timestamp,
		resolve,
		"Set Unit" if scanned["type"] == "set" else None,
		scanned["id"],
		raw.strip(),
	)


# --- Sinh Cycle ID, in lại, hủy -------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*PACKING_ROLES)
@idempotent
def generate_cycle_id(
	set_id, station, confirmed_lines, ci_batch, pack_type, maint_actions=None, client_ts=None, token=None
):
	"""Sinh Cycle ID cho bộ tại T4 (FR-M2-07/08) trong một transaction; trả gói, HRI, DataMatrix và lệnh in.

	`confirmed_lines` là mã dụng cụ đã tick; `maint_actions` là xử lý các nhắc bảo dưỡng
	(``[{"instrument", "action": "Done"|"Deferred", "oil_batch"?, "reason"?}]``); cả hai nhận list hoặc chuỗi JSON.
	Cảnh báo in (``NO_PRINTER_FOR_METHOD``, ``LABEL_TEMPLATE_MISSING``, ``LABEL_RENDER_FAILED``) nằm trong
	``print.warning`` của kết quả thành công: Cycle ID vẫn giữ, không phải lỗi HTTP.
	"""
	require_any_role(*PACKING_ROLES)
	frappe.has_permission("Pack", "create", throw=True)  # trước mọi thao tác ghi, kể cả Audit Log
	confirmed = _confirmed_lines(confirmed_lines)
	actions = _maint_actions(maint_actions)
	timestamp = parse_client_ts(client_ts)
	scanned = gs1.parse_scan(set_id)
	is_set = scanned["type"] == "set"
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {
			"ok": True,
			**packing.generate(set_id, station, confirmed, ci_batch, pack_type, actions, timestamp),
		},
		"Set Unit" if is_set else None,
		scanned["id"] if is_set else None,
		scanned["raw"],
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*PACKING_ROLES)
@idempotent
def reprint_label(cycle_id, reason, station, client_ts=None, token=None):
	"""In lại nhãn cùng Cycle ID trong 10 phút kể từ khi sinh (AC-10); cần lý do."""
	require_any_role(*PACKING_ROLES)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {"ok": True, **packing.reprint(cycle_id, reason, station)},
		"Pack",
		cycle_id,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*PACKING_ROLES)
@idempotent
def void(cycle_id, reason, station, note=None, client_ts=None, token=None):
	"""Hủy Cycle ID tại T4 (D12): `reason` là một lý do hủy của Pack; bộ về Reprocess để đóng gói lại."""
	require_any_role(*PACKING_ROLES)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(
		STEP,
		station,
		timestamp,
		lambda: {"ok": True, **packing.void(cycle_id, reason, station, note)},
		"Pack",
		cycle_id,
	)
