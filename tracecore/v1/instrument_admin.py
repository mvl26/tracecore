"""RPC tracecore.v1.instrument_admin.*: thao tác quản trị dụng cụ từ Desk (FEAT-014 Task 4; A-06 I6, I13, I15).

`init_counters` (khởi tạo bộ đếm bảo dưỡng từ lần bảo dưỡng gần nhất, FR-M1-09) và `retire` (ngừng sử dụng,
UC-01 E3). Chỉ TC R02, TC R10 và System Manager; quyền kiểm TRƯỚC mọi thao tác ghi (bộ đếm lưu bằng
ignore_permissions). Từ chối nghiệp vụ: body chuẩn ``{"ok": false, "error"}`` + mã HTTP + Audit Log `Reject`.
"""

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.instrument import catalog, maintenance
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

ADMIN_ROLES = ("TC R02", "TC R10", "System Manager")
INIT_SAVEPOINT = "tc_instrument_init_counters"
RETIRE_FIELDS = ("name", "status", "retired_on", "retired_reason")


def _text(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be text.").format(name))
	return value


def _not_found(instrument):
	return Block(
		"INSTRUMENT_NOT_FOUND",
		_("Instrument not found"),
		_("Instrument {0} not found.").format(instrument or "-"),
		_("Check the instrument code or call R02."),
	)


def _rows(rows):
	"""`rows` (list hoặc JSON) thành danh sách dict; sai định dạng → BadRequestError (400)."""
	if isinstance(rows, str):
		try:
			rows = frappe.parse_json(rows)
		except Exception:
			raise BadRequestError(_("rows must be a JSON list.")) from None
	if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
		raise BadRequestError(
			_("rows must be a list of objects with set_unit, cycles_since and last_maint_on.")
		)
	# set_unit phải là chuỗi trước khi kiểm trùng (list/dict không băm được → 500 nếu không chặn ở đây)
	for row in rows:
		if not isinstance(row.get("set_unit"), str):
			raise BadRequestError(_("{0} must be text.").format("set_unit"))
	return rows


@frappe.whitelist(methods=["POST"])
@idempotent
def init_counters(instrument, rows, reason, client_ts=None):
	"""Khởi tạo bộ đếm bảo dưỡng của `instrument` cho từng bộ trong `rows` (cả loạt một transaction).

	``rows = [{set_unit, cycles_since, last_maint_on}]`` (``last_maint_on`` tùy chọn). Thành công:
	``{"ok": true, "instrument", "counters": [{set_unit, instrument, name}]}``. Từ chối (không dòng nào được ghi):
	``INSTRUMENT_NOT_FOUND`` (404), ``REASON_REQUIRED`` (422), ``SET_NOT_FOUND`` (404), ``COUNTER_INIT_INVALID`` (422:
	danh sách rỗng, bộ trùng, số chu trình/ngày sai, bộ không chứa dụng cụ, đã có lịch sử T4); ``items`` chỉ dòng lỗi.
	"""
	require_any_role(*ADMIN_ROLES)
	timestamp = parse_client_ts(client_ts)
	instrument = _text(instrument, "instrument")
	reason = _text(reason, "reason")
	rows = _rows(rows)

	def reject(block):
		return reject_block(block, "Instrument", instrument, client_ts=timestamp)

	if not instrument or not frappe.db.exists("Instrument", instrument):
		return reject(_not_found(instrument))
	if not (reason or "").strip():
		return reject(
			Block(
				"REASON_REQUIRED",
				_("Reason is required"),
				_("A reason is required to initialize a maintenance counter."),
				_("Enter where the cycle count comes from, for example the paper maintenance log."),
			)
		)
	if not rows:
		return reject(maintenance.init_block(_("No set was given.")))
	seen = set()
	for index, row in enumerate(rows, 1):
		if row.get("set_unit") in seen:
			block = maintenance.init_block(_("Set {0} is listed more than once.").format(row.get("set_unit")))
			block.items = [{"row": index, "set_unit": row.get("set_unit")}]
			return reject(block)
		seen.add(row.get("set_unit"))

	counters = []
	frappe.db.savepoint(INIT_SAVEPOINT)
	for index, row in enumerate(rows, 1):
		try:
			name = maintenance.init_counter(
				row.get("set_unit"), instrument, row.get("cycles_since"), row.get("last_maint_on"), reason
			)
		except BlockedError as error:
			frappe.db.rollback(save_point=INIT_SAVEPOINT)
			block = error.block
			block.items = [{"row": index, "set_unit": row.get("set_unit")}]
			return reject(block)
		counters.append({"set_unit": row.get("set_unit"), "instrument": instrument, "name": name})
	return {"ok": True, "instrument": instrument, "counters": counters}


@frappe.whitelist(methods=["POST"])
@idempotent
def retire(instrument, reason, confirm=0, client_ts=None):
	"""Ngừng sử dụng dụng cụ (một chiều, bắt buộc lý do); còn trong BOM hiện hành thì phải gọi lại với ``confirm=1``.

	Thành công: ``{"ok": true, "instrument": {name, status, retired_on, retired_reason}, "boms": [...]}``.
	Từ chối: ``INSTRUMENT_NOT_FOUND`` (404), ``REASON_REQUIRED`` (422), ``INSTRUMENT_RETIRED`` (409),
	``INSTRUMENT_IN_BOM`` (409, ``error.boms`` = loại bộ có BOM hiện hành chứa dụng cụ; chưa ghi gì).
	"""
	require_any_role(*ADMIN_ROLES)
	timestamp = parse_client_ts(client_ts)
	instrument = _text(instrument, "instrument")
	reason = (_text(reason, "reason") or "").strip()

	def reject(block):
		return reject_block(block, "Instrument", instrument, client_ts=timestamp)

	status = frappe.db.get_value("Instrument", instrument, "status") if instrument else None
	if not status:
		return reject(_not_found(instrument))
	if not reason:
		return reject(
			Block(
				"REASON_REQUIRED",
				_("Reason is required"),
				_("A reason is required to retire an instrument."),
				_("Enter the reason for retiring this instrument."),
			)
		)
	if status == "Retired":
		return reject(
			Block(
				"INSTRUMENT_RETIRED",
				_("Instrument already retired"),
				_("Instrument {0} is already retired.").format(instrument),
				_("A retired instrument cannot be returned to use. Declare a new instrument if needed."),
			)
		)
	result = catalog.retire(instrument, reason, confirm)
	if not result["retired"]:
		boms = result["boms"]
		body = reject(
			Block(
				"INSTRUMENT_IN_BOM",
				_("Instrument is in a current BOM"),
				_("Instrument {0} is in the current BOM of: {1}.").format(
					instrument, ", ".join(row["set_type"] for row in boms)
				),
				_("Confirm to retire it anyway; review these BOMs afterwards."),
				items=boms,
			)
		)
		body["error"]["boms"] = boms
		return body
	values = frappe.db.get_value("Instrument", instrument, list(RETIRE_FIELDS), as_dict=True)
	# chuỗi thuần để response lưu (JSON) và response trả lần đầu giống nhau
	return {
		"ok": True,
		"instrument": {key: None if value is None else str(value) for key, value in values.items()},
		"boms": result["boms"],
	}
