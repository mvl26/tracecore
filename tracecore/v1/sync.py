"""RPC tracecore.v1.sync.* — đồng bộ offline của trạm/PDA (FEAT-009, ADR-003, A-40 D2, D4, D5).

- `snapshot`: dữ liệu đọc để trạm T1/T4/PDA T8 kiểm khi mất mạng (kiosk làm mới 10 phút một lần khi online).
  Bước khác trả ``offline: false`` (Q1: các bước đó vẫn chặn khi mất mạng).
- `status`: số xung đột đang mở cho R02. `resolve`: R02 đóng một xung đột.
Phát lại không có RPC riêng: kiosk gọi lại RPC gốc với header ``X-TC-Replay: 1`` (xem `core.sync`).
"""

import contextlib

import frappe
from frappe.utils import cint, getdate, today

from tracecore.core import code_range, crypto, extension, step_gate, sync, zones
from tracecore.core.client_time import parse_client_ts, to_system_time
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import packing, receiving, usage
from tracecore.v1._common import (
	PACKING_ROLES,
	RECEIVE_ROLES,
	USAGE_ROLES,
	current_station_session,
	require_any_role,
	station_session,
)

OFFLINE_FUNCTIONS = ("RECEIVE", "PACK", "USE")  # chức năng có màn chạy offline (A-40)
SNAPSHOT_ROLES = tuple(dict.fromkeys((*RECEIVE_ROLES, *PACKING_ROLES, *USAGE_ROLES)))
STATUS_ROLES = ("TC R02", "TC R01", "TC R10", "System Manager")
SAVEPOINT = "tc_sync_snapshot"


def _bom_lines(lines):
	return [
		{
			"instrument": line["instrument"],
			"instrument_name": line.get("instrument_name"),
			"qty": cint(line.get("qty")),
			"position": cint(line.get("position")),
			"thumbnail": line.get("thumbnail") or line.get("image_thumbnail"),
			"image": line.get("image"),
		}
		for line in lines or []
	]


def _t1(on):
	"""Bộ T1 nhận được (trạng thái hợp T1) kèm BOM áp dụng tại `on`, và danh sách khoa cho người giao không thẻ."""
	units = frappe.get_all(
		"Set Unit",
		filters={"status": ["in", step_gate.STATION_STATUSES["T1"]]},
		fields=["name", "set_type", "status", "department"],
		order_by="name asc",
	)
	names = dict(
		frappe.get_all(
			"Instrument Set Type",
			filters={"name": ["in", list({u.set_type for u in units}) or [""]]},
			fields=["name", "set_type_name"],
			as_list=True,
		)
	)
	sets = []
	for unit in units:
		context = {}
		for part in extension.run(
			receiving.RECEIPT_CONTEXT_HOOK, {"set_unit": unit.name, "set_type": unit.set_type, "on": on}
		):
			context.update(part)
		sets.append(
			{
				"set_id": unit.name,
				"set_type": unit.set_type,
				"set_name": names.get(unit.set_type),
				"status": unit.status,
				"department": unit.department,
				"bom": _bom_lines(context.get("bom")),
			}
		)
	return {"sets": sets, "departments": receiving.departments()}


def _t4_row(set_id, station):
	"""Ngữ cảnh T4 của một bộ như màn online; bị chặn → dòng có ``blocked``. Mọi ghi phụ (vd PAR_EXCEEDED chuyển bộ
	sang Hết vòng đời) bị hoàn tác: snapshot chỉ đọc, việc chặn thật xảy ra khi phát lại."""
	frappe.db.savepoint(SAVEPOINT)
	try:
		ctx = packing.get_context(set_id, station)
	except BlockedError as error:
		block = error.block.as_dict()
		return {"set_id": set_id, "blocked": block, "par_blocked": block["code"] == "PAR_EXCEEDED"}
	finally:
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
	info = ctx["set"]
	return {
		"set_id": info["set_id"],
		"set_type": info["set_type"],
		"set_name": info["set_name"],
		"method": info["method"],
		"department": info["department"],
		"is_loaner": info["is_loaner"],
		"bom": _bom_lines(ctx["bom"]),
		"short_lines": ctx["shortage"],
		"par_blocked": False,
		"maint_pending": bool(ctx.get("maintenance")),
		"pack_types": ctx["pack_types"],
		"blocked": None,
		# ngữ cảnh đầy đủ như `pack.scan` online để màn T4 vẽ y hệt khi offline (máy in không dùng được khi offline)
		"context": {**ctx, "printer": None},
	}


def _ci_batches():
	"""Lô chỉ thị loại 5/6 còn dùng được (cùng điều kiện `packing.resolve_ci_batch`, trừ hạn kiểm lúc đóng gói)."""
	return frappe.db.sql(
		"""select b.name as batch, i.tc_compatible_method as method, i.tc_ci_class as ci_class,
			b.expiry_date as expiry
		from `tabBatch` b join `tabItem` i on i.name = b.item
		where i.tc_item_group_cssd = 'Chemical Indicator' and i.tc_ci_class in %(classes)s
			and ifnull(i.tc_compatible_method, '') != '' and b.disabled = 0
			and b.expiry_date is not null and b.expiry_date >= %(today)s
		order by b.expiry_date asc""",
		{"classes": packing.CI_CLASSES, "today": today()},
		as_dict=True,
	)


def _t4(station, on, session):
	units = frappe.get_all(
		"Set Unit",
		filters={"status": ["in", step_gate.STATION_STATUSES["T4"]]},
		pluck="name",
		order_by="name asc",
	)
	ready = [name for name in units if step_gate.check(name, "T4") is None]
	ranges = code_range.ensure(station, on, session)
	return {
		"sets": [_t4_row(name, station) for name in ready],
		"ci_batches": [{**row, "expiry": str(row.expiry)} for row in _ci_batches()],
		"ranges": [{**row, "expires_at": str(row["expires_at"])} for row in ranges],
	}


def _t8(employee):
	"""Gói Đã cấp phát cho khoa của nhân viên, còn hạn, bộ đang Tại khoa (FR-M2-18 theo snapshot) + public key mã BN."""
	department = frappe.db.get_value("Employee", employee, "department") if employee else None
	packs = frappe.get_all(
		"Pack",
		filters={"status": usage.ISSUED, "expiry": [">=", getdate(today())]},
		fields=["name", "set_unit", "set_type", "set_name", "method", "status", "expiry", "department"],
		order_by="expiry asc",
	)
	rows = []
	for pack in packs:
		pack_department = usage._pack_department(pack)
		if department and pack_department != department:
			continue
		if frappe.db.get_value("Set Unit", pack.set_unit, "status") != "At Department":
			continue
		rows.append(
			{
				"cycle_id": pack.name,
				"set_id": pack.set_unit,
				"set_name": pack.set_name,
				"method": pack.method,
				"status": pack.status,
				"expiry": str(pack.expiry),
				"department": pack_department,
			}
		)
	return {"packs": rows, "department": department, "patient_key": crypto.patient_public_key()}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*SNAPSHOT_ROLES)
def snapshot(station, client_ts=None, token=None):
	"""Dữ liệu đọc offline của trạm theo chức năng (A-40 D4, A-64): ``{"ok": true, "function", ...}``."""
	require_any_role(*SNAPSHOT_ROLES)
	functions = zones.station_functions(station)
	function = next((code for code in OFFLINE_FUNCTIONS if code in functions), None)
	on = to_system_time(parse_client_ts(client_ts))
	session = current_station_session()
	if function == "RECEIVE":
		data = _t1(on)
	elif function == "PACK":
		data = _t4(station, on.date(), session.name if session else None)
	elif function == "USE":
		data = _t8(session.employee if session else None)
	else:
		return {"ok": True, "function": functions[0] if functions else None, "offline": False}
	return {"ok": True, "function": function, "offline": True, **data}


@frappe.whitelist(methods=["GET", "POST"])
def status(station=None):
	"""Số Sync Conflict đang mở (của trạm nếu có) cho R02: ``{"open_conflicts", "last_conflict"}``."""
	require_any_role(*STATUS_ROLES)
	filters = {"status": "Open", **({"station": station} if station else {})}
	last = frappe.get_all("Sync Conflict", filters=filters, pluck="name", order_by="creation desc", limit=1)
	return {
		"open_conflicts": frappe.db.count("Sync Conflict", filters),
		"last_conflict": last[0] if last else None,
	}


@frappe.whitelist(methods=["POST"])
def resolve(name, note=None):
	"""R02/R01 đóng một Sync Conflict kèm cách xử lý (Desk, SCR-33)."""
	return {"ok": True, "name": sync.resolve(name, note)}
