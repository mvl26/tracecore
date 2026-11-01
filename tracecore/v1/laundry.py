"""RPC tracecore.v1.laundry.* — màn lô giặt theo kg (SCR-17, FEAT-034, UC-17, FR-M3-03, FR-M3-04).

Lớp mỏng trên `tracecore.linen.laundry`, theo khuôn `v1.linen`: phiên thẻ nhân viên (`station_session`, token trong body) →
`@idempotent` → kiểm định dạng tham số (400) → gọi dịch vụ. Từ chối nghiệp vụ (`BlockedError`) thành
``{"ok": false, "error": {...}}`` (xem `_common.run_at_step`). Mọi RPC chỉ chạy ở trạm bước LIN (trạm đồ vải, A-49 L1, A-50 D1);
người vận hành là Employee của phiên thẻ, không nhận từ tham số.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, today

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.costing import from_laundry
from tracecore.linen import laundry
from tracecore.linen import machine_usage as usage_of_machine
from tracecore.v1._common import (
	LINEN_ROLES,
	BadRequestError,
	current_station_session,
	reject_block,
	require_any_role,
	run_at_step,
	station_session,
)

FUNCTION = "LINEN"
BATCH_TYPES = (laundry.IN_HOUSE, laundry.OUTSOURCED)


def _text(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be a string.").format(name))
	return value or None


def _rows(value, name):
	"""`name` là list (hoặc chuỗi JSON của list) các object; không có → None (dịch vụ trả mã lỗi nghiệp vụ)."""
	if value is None:
		return None
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			raise BadRequestError(_("{0} must be a list of objects.").format(name)) from None
	if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
		raise BadRequestError(_("{0} must be a list of objects.").format(name))
	return value


def _operator():
	session = current_station_session()
	return session.employee if session else None


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LINEN_ROLES)
def context(station, client_ts=None, token=None):
	"""Máy giặt/sấy Sẵn sàng, chương trình, hóa chất và lô đang chạy; chỉ đọc, không ghi Idempotency Key."""
	require_any_role(*LINEN_ROLES)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(FUNCTION, station, timestamp, lambda: {"ok": True, **laundry.context()})


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LINEN_ROLES)
@idempotent
def start(
	station,
	loads=None,
	equipment=None,
	program=None,
	chemicals=None,
	batch_type=laundry.IN_HOUSE,
	vendor=None,
	price_per_kg=None,
	redo_of=None,
	note=None,
	client_ts=None,
	token=None,
	dryer=None,
	dry_program=None,
):
	"""Tạo lô giặt Đang chạy: `loads` = ``[{"kg", "contaminated"}]``, `chemicals` = ``[{"item", "qty"}]`` (không bắt buộc).

	Trả ``{"ok": true, "batch": {...}}``.
	"""
	require_any_role(*LINEN_ROLES)
	loads = _rows(loads, "loads")
	chemicals = _rows(chemicals, "chemicals")
	equipment, program = _text(equipment, "equipment"), _text(program, "program")
	dryer, dry_program = _text(dryer, "dryer"), _text(dry_program, "dry_program")
	vendor, redo_of, note = _text(vendor, "vendor"), _text(redo_of, "redo_of"), _text(note, "note")
	if batch_type not in BATCH_TYPES:
		raise BadRequestError(_("batch_type must be one of {0}.").format(", ".join(BATCH_TYPES)))
	timestamp = parse_client_ts(client_ts)

	def call():
		doc = laundry.start(
			station,
			_operator(),
			loads,
			equipment=equipment,
			program=program,
			chemicals=chemicals,
			batch_type=batch_type,
			vendor=vendor,
			price_per_kg=price_per_kg,
			redo_of=redo_of,
			note=note,
			dryer=dryer,
			dry_program=dry_program,
		)
		return {"ok": True, "batch": laundry.view(doc)}

	return run_at_step(FUNCTION, station, timestamp, call, None, None)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*LINEN_ROLES)
@idempotent
def complete(
	station,
	batch=None,
	dryer=None,
	dry_temp_c=None,
	dry_minutes=None,
	clean_ok=None,
	dry_ok=None,
	note=None,
	client_ts=None,
	token=None,
	dry_program=None,
	actual_kwh=None,
	actual_dry_kwh=None,
	actual_water_l=None,
	deviation_reason=None,
):
	"""Hoàn tất lô: ghi sấy và kết quả, trừ hóa chất, tính chi phí/kg. Trả ``{"ok": true, "batch": {...}}`` kèm chi phí."""
	require_any_role(*LINEN_ROLES)
	batch, dryer, note = _text(batch, "batch"), _text(dryer, "dryer"), _text(note, "note")
	dry_program = _text(dry_program, "dry_program")
	deviation_reason = _text(deviation_reason, "deviation_reason")
	timestamp = parse_client_ts(client_ts)

	def call():
		doc = laundry.complete(
			batch,
			dryer=dryer,
			dry_temp_c=dry_temp_c,
			dry_minutes=dry_minutes,
			clean_ok=clean_ok,
			dry_ok=dry_ok,
			note=note,
			dry_program=dry_program,
			actual_kwh=actual_kwh,
			actual_dry_kwh=actual_dry_kwh,
			actual_water_l=actual_water_l,
			deviation_reason=deviation_reason,
		)
		return {"ok": True, "batch": laundry.view(doc)}

	return run_at_step(FUNCTION, station, timestamp, call, "Laundry Batch", batch)


@frappe.whitelist()
def program_norm(program=None):
	"""Định mức và chi phí định mức theo mẻ, theo kg của chương trình giặt/sấy tại hôm nay (Desk, #1847 DV-02); chỉ đọc."""
	frappe.has_permission("Process Program", "read", throw=True)
	if not _text(program, "program") or not frappe.db.exists("Process Program", program):
		raise BadRequestError(_("Program {0} does not exist.").format(program or "-"))
	return from_laundry.norm_breakdown([program])


@frappe.whitelist()
def norm_preview(program=None, dry_program=None, kg=None):
	"""Định mức và chi phí định mức của lô đang lập trên form Desk (#1847 DV-03); chỉ đọc, không ghi lô."""
	frappe.has_permission("Laundry Batch", "read", throw=True)
	programs = [_text(program, "program"), _text(dry_program, "dry_program")]
	for name in filter(None, programs):
		if not frappe.db.exists("Process Program", name):
			raise BadRequestError(_("Program {0} does not exist.").format(name))
	return from_laundry.norm_breakdown(programs, kg=flt(kg))


@frappe.whitelist(methods=["POST"])
@idempotent
def complete_desk(
	batch=None,
	dryer=None,
	dry_program=None,
	dry_temp_c=None,
	dry_minutes=None,
	clean_ok=None,
	dry_ok=None,
	note=None,
	deviation_reason=None,
	client_ts=None,
):
	"""Nút Hoàn tất lô trên form Desk (A-104 D8): cùng dịch vụ với trạm; số thực tế đọc từ lô đã lưu."""
	require_any_role(*LINEN_ROLES)
	timestamp = parse_client_ts(client_ts)
	batch = _text(batch, "batch")
	try:
		doc = laundry.complete(
			batch,
			dryer=_text(dryer, "dryer"),
			dry_temp_c=dry_temp_c,
			dry_minutes=dry_minutes,
			clean_ok=clean_ok,
			dry_ok=dry_ok,
			note=_text(note, "note"),
			dry_program=_text(dry_program, "dry_program"),
			deviation_reason=_text(deviation_reason, "deviation_reason"),
		)
	except BlockedError as error:
		return reject_block(error.block, "Laundry Batch", batch, client_ts=timestamp)
	return {"ok": True, "batch": laundry.view(doc)}


@frappe.whitelist()
def machine_usage(equipment=None, from_date=None, to_date=None):
	"""Khối Sử dụng trên form máy giặt, máy sấy (#1847 DV-04); chỉ đọc, lô theo quyền người xem."""
	frappe.has_permission("Laundry Batch", "read", throw=True)
	frappe.has_permission("Equipment", "read", throw=True)
	equipment = _text(equipment, "equipment")
	if not equipment or not frappe.db.exists("Equipment", equipment):
		raise BadRequestError(_("Equipment {0} does not exist.").format(equipment or "-"))
	day = today()
	return usage_of_machine.usage(equipment, from_date or day, to_date or day)
