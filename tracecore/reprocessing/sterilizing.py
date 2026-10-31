"""Mẻ tiệt khuẩn tại T5 (M2, FEAT-022, UC-09): quy tắc máy và nhận gói, Hoàn thành nạp, tra cứu mẻ, dữ liệu nhập tay.

- Quy tắc: `check_equipment_ready`, `capacity_of`, `scan_machine`, `admit_pack`, `running_loads`.
- Dịch vụ trạm T5: `complete` (Hoàn thành nạp: sinh mã mẻ `ME-`, gói sang Trong mẻ, in nhãn QR); `lookup` (tra cứu mẻ);
  `scan_for_data`, `data_context`, `save_manual_data` (dữ liệu chu trình nhập tay có xác nhận thẻ, FR-M2-10).

Nạp mẻ không ghi cổng T5 và không đổi trạng thái Set Unit: cổng T5 ghi khi giải phóng (FEAT-023). M2 không import
`tracecore.equipment` (lint R1): máy, chương trình đọc bằng tên DocType như `washing`. Mẻ chỉ do module này tạo/đổi bằng cờ
``flags.tc_sterilizing`` của Sterilization Load, gói bằng cờ ``flags.tc_packing`` của Pack. Từ chối nghiệp vụ là
`BlockedError` (mã HTTP ở `core.errors`).
"""

import base64
import contextlib
import re
from datetime import timezone
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, get_datetime, getdate, now_datetime
from frappe.utils.data import get_system_timezone

from tracecore.core import client_time, extension, gs1, qr, station_auth, step_gate, zones
from tracecore.core import print as core_print
from tracecore.core.errors import Block, BlockedError

STEP = "T5"  # mã cổng trong step_gate
FUNCTION = "STERI_LOAD"
UNLOAD_FUNCTION = "STERI_UNLOAD"
LOAD_OR_UNLOAD = (FUNCTION, UNLOAD_FUNCTION)
SAVEPOINT = "tc_load_complete"
# loại máy tiệt khuẩn → phương pháp của gói nhận được (Pack.method)
STERILIZER_TYPES = {"Steam Sterilizer": "Steam", "Plasma Sterilizer": "Plasma"}
RUNNING = "Running"
CYCLE_COMPLETE = "Cycle Complete"
OPEN_STATUSES = (RUNNING, CYCLE_COMPLETE)
LOADABLE = "Packed"
IN_LOAD = "In Load"
EQUIPMENT_CHECKS_HOOK = "tracecore_load_equipment_checks"
AFTER_COMPLETE_HOOK = "tracecore_after_load_complete"
# mục thiếu của dữ liệu chu trình ngoài tên tham số (kiosk dịch sang chữ)
MISSING_ENDED_AT = "ended_at"
MISSING_PRINTOUT = "printout"
MISSING_REASON = "reason"
MISSING_CONFIRMATION = "confirmation"
MISSING_CARD = "card"
EQUIPMENT_FIELDS = (
	"name equipment_name equipment_type status zone_in zone_out is_connected has_printout capacity".split()
)
INDICATORS = {
	"Steam": ("chemical_class_5", "bowie_dick"),
	"Plasma": ("chemical_plasma",),
}


def _blocked(code, title, reason, action, items=None, **fields):
	return BlockedError(Block(code, title, reason, action, items=items, **fields))


def _today():
	"""Ngày hôm nay theo giờ hệ thống (Asia/Ho_Chi_Minh), không theo UTC."""
	return getdate(now_datetime())


def _system_time(client_ts):
	"""`client_ts` UTC không múi giờ → giờ hệ thống (Asia/Ho_Chi_Minh) không múi giờ (ADR-003)."""
	utc = get_datetime(client_ts).replace(tzinfo=timezone.utc)
	return utc.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


# --- Máy tiệt khuẩn (FR-M2-09.3, FR-M2-09.5) -------------------------------------------------------------


def check_equipment_ready(equipment):
	"""Block nếu `equipment` không dùng được để nạp mẻ, ngược lại None.

	Thứ tự: không có máy → EQUIPMENT_NOT_FOUND; không phải máy hấp hơi nước/plasma → EQUIPMENT_NOT_STERILIZER; trạng thái
	khác Sẵn sàng → EQUIPMENT_NOT_READY; máy còn mẻ chưa xong chu trình (`Running`) → EQUIPMENT_BUSY (A-22: một máy chỉ
	chạy một mẻ); rồi hook ``tracecore_load_equipment_checks`` (FEAT-040: test ngày, kiểm định) — hàm hook trả `Block`
	thì chặn (A-16, Q3).
	"""
	row = frappe.db.get_value("Equipment", equipment, ["equipment_type", "status"], as_dict=True)
	if not row:
		return Block(
			"EQUIPMENT_NOT_FOUND",
			_("Equipment not found"),
			_("Equipment {0} does not exist.").format(equipment or "-"),
			_("Scan the QR code on the sterilizer."),
		)
	if row.equipment_type not in STERILIZER_TYPES:
		return Block(
			"EQUIPMENT_NOT_STERILIZER",
			_("Not a sterilizer"),
			_("Equipment {0} is a {1}, not a steam or plasma sterilizer.").format(
				equipment, _(row.equipment_type)
			),
			_("Scan the QR code of a steam or plasma sterilizer."),
		)
	if row.status != "Ready":
		return Block(
			"EQUIPMENT_NOT_READY",
			_("Sterilizer is not ready"),
			_("Equipment {0} is {1}.").format(equipment, _(row.status, context="Equipment")),
			_("Use another sterilizer, or call R02 to check the daily test and the inspection."),
			object_type="Equipment",
			object_name=equipment,
		)
	running = frappe.db.get_value(
		"Sterilization Load", {"equipment": equipment, "status": "Running", "docstatus": 0}, "name"
	)
	if running:
		return Block(
			"EQUIPMENT_BUSY",
			_("Sterilizer is still running a load"),
			_("Load {0} on sterilizer {1} has no cycle data yet.").format(running, equipment),
			_("Enter the cycle data of load {0} first, then load this sterilizer again.").format(running),
		)
	for block in extension.run(EQUIPMENT_CHECKS_HOOK, equipment):
		if isinstance(block, Block):
			return block
	return None


def capacity_of(equipment):
	"""Số gói tối đa của một mẻ trên máy `equipment`, hoặc None nếu không giới hạn (A-16, Q4).

	``Equipment.capacity`` là Data tự do ("Dung tích (STU/kg)" trong BA); số nguyên đầu tiên trong đó là số gói tối đa,
	trống, không có số hoặc bằng 0 → không giới hạn.
	"""
	match = re.search(r"\d+", frappe.db.get_value("Equipment", equipment, "capacity") or "")
	return (int(match.group()) or None) if match else None


def _parameters(program):
	return frappe.get_all(
		"Program Parameter",
		filters={"parent": program, "parenttype": "Process Program"},
		fields=["parameter_name", "unit", "min_value", "max_value", "required"],
		order_by="idx asc",
	)


def _compatible_pack_types(program):
	return frappe.get_all(
		"Program Compatible Pack Type",
		filters={"parent": program, "parenttype": "Process Program"},
		pluck="pack_type",
		order_by="idx asc",
	)


def _indicators(equipment_type, requires_bi):
	codes = list(INDICATORS[STERILIZER_TYPES[equipment_type]])
	if cint(requires_bi):
		codes.append("biological")
	return codes


def scan_machine(raw):
	"""Mở phiên nạp từ mã QR máy: máy, chương trình đang dùng của máy (FR-M2-09.1, .3).

	``{"equipment": {..., "method", "max_packs"}, "programs": [...]}``; mỗi chương trình có ``compatible_pack_types``,
	``parameters`` (param_schema) và ``indicators``. Mã không phải máy → SCAN_INVALID; máy không dùng được →
	`check_equipment_ready`.
	"""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "equipment":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} is not a sterilizer QR code.").format(scanned["raw"] or "-"),
			_("Scan the QR code on the sterilizer."),
		)
	block = check_equipment_ready(scanned["id"])
	if block:
		raise BlockedError(block)
	equipment = frappe.db.get_value("Equipment", scanned["id"], list(EQUIPMENT_FIELDS), as_dict=True)
	equipment.is_connected = cint(equipment.is_connected)
	equipment.has_printout = cint(equipment.has_printout)
	equipment.method = STERILIZER_TYPES[equipment.equipment_type]
	equipment.max_packs = capacity_of(equipment.name)
	programs = [
		{
			"program_code": row.name,
			"program_name": row.program_name,
			"requires_bi": cint(row.requires_bi),
			"compatible_pack_types": _compatible_pack_types(row.name),
			"parameters": _parameters(row.name),
			"indicators": _indicators(equipment.equipment_type, row.requires_bi),
		}
		for row in frappe.get_all(
			"Process Program",
			filters={"equipment": equipment.name, "is_active": 1},
			fields=["name", "program_name", "requires_bi"],
			order_by="program_name asc",
		)
	]
	return {"equipment": equipment, "programs": programs}


def _program(equipment, program):
	"""Chương trình `program` của máy `equipment` còn dùng, hoặc PROGRAM_INVALID."""
	row = frappe.db.get_value(
		"Process Program",
		program,
		["name", "program_name", "equipment", "is_active", "requires_bi"],
		as_dict=True,
	)
	if not row or row.equipment != equipment or not cint(row.is_active):
		raise _blocked(
			"PROGRAM_INVALID",
			_("Program is not valid"),
			_("Program {0} is not an active program of equipment {1}.").format(program or "-", equipment),
			_("Choose a program from the list of this sterilizer."),
		)
	return row


# --- Nhận gói vào mẻ (FR-M2-09.4 đến .6, BRU-REP-004, BRU-FLOW-004) --------------------------------------------


PACK_FIELDS = ("name", "set_unit", "cycle_no", "method", "pack_type", "expiry", "status", "load")


def _pack_not_found(raw):
	return _blocked(
		"PACK_NOT_FOUND",
		_("Pack not found"),
		_("Cycle ID {0} does not exist in TraceCore.").format(raw or "-"),
		_("Check the pack label or call R02."),
	)


def _not_loadable(pack, reason):
	return _blocked(
		"PACK_NOT_LOADABLE",
		_("Pack cannot be loaded"),
		reason,
		_("Check the pack status, or call R02."),
	)


def _check_compatible(pack, equipment_type, program):
	"""Block PACK_INCOMPATIBLE nếu phương pháp hoặc loại gói của `pack` không hợp máy/chương trình (BRU-REP-004)."""
	method = STERILIZER_TYPES[equipment_type]
	if pack.method != method:
		return Block(
			"PACK_INCOMPATIBLE",
			_("Pack does not fit this sterilizer"),
			_("Pack {0} is for {1} sterilization, but this sterilizer runs {2} programs.").format(
				pack.name, _(pack.method), _(method)
			),
			_("Load the pack into a {0} sterilizer.").format(_(pack.method)),
		)
	allowed = _compatible_pack_types(program)
	if allowed and pack.pack_type not in allowed:
		return Block(
			"PACK_INCOMPATIBLE",
			_("Pack does not fit this program"),
			_("Pack {0} uses pack type {1}, which program {2} does not accept.").format(
				pack.name, pack.pack_type, program
			),
			_("Choose a program that accepts this pack type."),
		)
	return None


def admit_pack(raw, equipment, program, queued=None, for_update=False):
	"""Kiểm một Cycle ID quét vào mẻ trên máy `equipment`, chương trình `program`; không ghi.

	Trả ``{"cycle_id", "set_id", "set_name", "method", "pack_type", "pack_type_name", "expiry", "duplicate", "gates",
	"count", "capacity"}``. Gói đã có trong `queued` thì ``duplicate = True`` và không phải lỗi. Từ chối theo thứ tự
	(A-16, Q6): máy hợp lệ → chương trình thuộc máy → mã là Cycle ID → gói tồn tại → gói ở mẻ khác / không còn nạp được
	→ gói còn là Cycle ID hiện hành của bộ → còn hạn → cổng T4 Đạt (`step_gate.check`) → tương thích → dung tích.
	`for_update`: đọc Pack và Set Unit có khóa (dùng khi ghi ngay sau đó).
	"""
	block = check_equipment_ready(equipment)
	if block:
		raise BlockedError(block)
	equipment_type = frappe.db.get_value("Equipment", equipment, "equipment_type")
	program_row = _program(equipment, program)
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "pack":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} is not a Cycle ID.").format(scanned["raw"] or "-"),
			_("Scan the code on the pack label."),
		)
	pack = frappe.db.get_value(
		"Pack",
		{"name": scanned["id"], "docstatus": 1},
		list(PACK_FIELDS),
		as_dict=True,
		for_update=for_update,
	)
	if not pack:
		raise _pack_not_found(scanned["id"])
	queue = set(queued or [])
	capacity = capacity_of(equipment)
	if pack.name in queue:
		return _admitted(pack, duplicate=True, count=len(queue), capacity=capacity)
	if pack.status == IN_LOAD:
		raise _blocked(
			"PACK_IN_OTHER_LOAD",
			_("Pack is in another load"),
			_("Pack {0} is in sterilization load {1}.").format(pack.name, pack.load or "-"),
			_("Take the pack out of that load first, or scan another pack."),
		)
	if pack.status != LOADABLE:
		raise _not_loadable(
			pack,
			_("Pack {0} is {1}; only a packed pack can be loaded.").format(
				pack.name, _(pack.status, context="Pack")
			),
		)
	unit = frappe.db.get_value(
		"Set Unit",
		pack.set_unit,
		["active_cycle_id", "current_cycle_no"],
		as_dict=True,
		for_update=for_update,
	)
	if not unit or unit.active_cycle_id != pack.name or cint(unit.current_cycle_no) != cint(pack.cycle_no):
		raise _not_loadable(
			pack,
			_("Pack {0} is not the current Cycle ID of set {1}.").format(pack.name, pack.set_unit),
		)
	if pack.expiry and getdate(pack.expiry) < _today():
		raise _blocked(
			"PACK_EXPIRED",
			_("Pack has expired"),
			_("Pack {0} expired on {1}.").format(pack.name, formatdate(pack.expiry)),
			_("Take the set back to packing."),
		)
	block = step_gate.check(pack.set_unit, STEP, for_update)
	if block:
		raise BlockedError(block)
	block = _check_compatible(pack, equipment_type, program_row.name)
	if block:
		raise BlockedError(block)
	if capacity and len(queue) >= capacity:
		raise _blocked(
			"LOAD_CAPACITY_EXCEEDED",
			_("Sterilizer is full"),
			_("Sterilizer {0} takes at most {1} pack(s) per load.").format(equipment, capacity),
			_("Complete loading, then load the remaining packs in the next load."),
		)
	return _admitted(pack, duplicate=False, count=len(queue) + 1, capacity=capacity)


def _admitted(pack, duplicate, count, capacity):
	set_type = frappe.db.get_value("Set Unit", pack.set_unit, "set_type")
	return {
		"cycle_id": pack.name,
		"set_id": pack.set_unit,
		"set_name": frappe.db.get_value("Instrument Set Type", set_type, "set_type_name"),
		"method": pack.method,
		"pack_type": pack.pack_type,
		"pack_type_name": frappe.db.get_value("Item", pack.pack_type, "item_name"),
		"expiry": pack.expiry,
		"duplicate": duplicate,
		"gates": step_gate.gates(pack.set_unit),
		"count": count,
		"capacity": capacity,
	}


def running_loads():
	"""Mẻ chưa dỡ (`Running` hoặc `Cycle Complete`, chưa ghi sổ) để màn T5 hiện thẻ "Mẻ đang chạy"."""
	rows = frappe.get_all(
		"Sterilization Load",
		filters={"status": ["in", list(OPEN_STATUSES)], "docstatus": 0},
		fields=[
			"name",
			"equipment",
			"program",
			"status",
			"load_completed_at",
			"data_complete",
			"needs_review",
			"requires_bi",
			"is_priority",
		],
		order_by="load_completed_at asc, name asc",
	)
	return [
		{
			"load": row.name,
			"status": row.status,
			"equipment": row.equipment,
			"equipment_name": frappe.db.get_value("Equipment", row.equipment, "equipment_name"),
			"program": row.program,
			"program_name": frappe.db.get_value("Process Program", row.program, "program_name"),
			"load_completed_at": row.load_completed_at,
			"data_complete": cint(row.data_complete),
			"needs_review": cint(row.needs_review),
			"requires_bi": cint(row.requires_bi),
			"is_priority": cint(row.is_priority),
			"packs": frappe.get_all(
				"Load Pack", filters={"parent": row.name, "parenttype": "Sterilization Load"}, pluck="pack"
			),
		}
		for row in rows
	]


# --- Hoàn thành nạp (FR-M2-09, FR-M2-24.1, BRU-REP-016) -------------------------------------------------------


def _admit_all(packs, equipment, program):
	"""``(gói nhận được, gói bị loại)`` cho danh sách quét `packs`; gói bị loại là ``{"cycle_id", "code", "reason"}``.

	Khóa các Set Unit rồi các Pack theo thứ tự tên (cùng thứ tự với `packing.void`/`storage`) và kiểm lại từng gói
	bằng đọc có khóa: hai kiosk cùng nạp một gói thì chỉ một nơi giữ được. Quét lặp cùng gói chỉ tính một lần; gói vượt
	dung tích vào danh sách bị loại.
	"""
	scanned = [(raw, gs1.parse_scan(raw)) for raw in packs or []]
	names = sorted({s["id"] for _raw, s in scanned if s["type"] == "pack"})
	owners = sorted(
		(frappe.db.get_value("Pack", name, "set_unit") or "", name)
		for name in names
		if frappe.db.exists("Pack", {"name": name, "docstatus": 1})
	)
	for set_unit in sorted({owner for owner, _name in owners if owner}):
		frappe.db.get_value("Set Unit", set_unit, "name", for_update=True)
	for _owner, name in owners:
		frappe.db.get_value("Pack", name, "name", for_update=True)
	accepted, rejected = [], []
	for raw, parsed in scanned:
		try:
			admitted = admit_pack(raw, equipment, program, accepted, for_update=True)
		except BlockedError as error:
			rejected.append(
				{
					"cycle_id": parsed["id"] or parsed["raw"],
					"code": error.block.code,
					"reason": error.block.reason,
				}
			)
			continue
		if not admitted["duplicate"]:
			accepted.append(admitted["cycle_id"])
	return accepted, rejected


def complete(equipment, program, packs, station, client_ts, operator, is_priority=False):
	"""Hoàn thành nạp: sinh mã mẻ `ME-YYMMDD-NN` cho các gói quét vào máy, ghi mẻ `Running`, gói sang Trong mẻ, xếp lệnh in nhãn QR.

	`client_ts` là kết quả `parse_client_ts` (UTC); giờ nạp = giờ hệ thống của nó, lệch giờ server quá
	`client_time.max_skew_seconds()` → ClientTimestampError trước khi ghi gì. `operator` là Employee đăng nhập thẻ. Máy phải
	Sẵn sàng, chương trình thuộc máy (cả mẻ bị từ chối nếu sai). Gói nào không còn hợp lệ (bị mẻ khác lấy, vượt dung
	tích…) vào `rejected` mà không dừng mẻ; không còn gói nào → LOAD_EMPTY. Mọi lỗi hoàn tác về savepoint rồi ném lại:
	không còn mẻ, dòng Code Registry hay số series nào. In không bao giờ làm mất mã mẻ.

	Trả ``{"load", "packs", "rejected", "print": {"print_job", "status", "printer", "zpl", "warning"}, "qr_png_b64"}``.
	"""
	client_time.check_skew(client_ts)
	frappe.db.savepoint(SAVEPOINT)
	try:
		return _complete(equipment, program, packs, station, client_ts, operator, is_priority)
	except Exception:
		# Sau deadlock InnoDB đã hoàn tác cả transaction (savepoint không còn): giữ lỗi gốc, bỏ lỗi rollback
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _complete(equipment, program, packs, station, client_ts, operator, is_priority):
	block = check_equipment_ready(equipment)
	if block:
		raise BlockedError(block)
	machine = frappe.db.get_value("Equipment", equipment, ["equipment_name", "equipment_type"], as_dict=True)
	program_row = _program(equipment, program)
	accepted, rejected = _admit_all(packs, equipment, program_row.name)
	if not accepted:
		raise _blocked(
			"LOAD_EMPTY",
			_("No pack can be loaded"),
			_("None of the scanned packs can go into a sterilization load on {0}.").format(equipment),
			_("Scan packs that have passed packing, then complete loading again."),
			items=rejected or None,
		)
	started = _system_time(client_ts)
	rows = [
		{
			"pack": name,
			"set_unit": frappe.db.get_value("Pack", name, "set_unit"),
			"added_at": started,
		}
		for name in accepted
	]
	load = frappe.get_doc(
		{
			"doctype": "Sterilization Load",
			"equipment": equipment,
			"program": program_row.name,
			"operator": operator,
			"status": RUNNING,
			"is_priority": 1 if is_priority else 0,
			"requires_bi": cint(program_row.requires_bi),
			"loaded_by_scan": 1,
			"load_completed_at": started,
			"started_at": started,
			"packs": rows,
		}
	)
	load.flags.tc_sterilizing = True
	load.insert(ignore_permissions=True)
	for name in accepted:
		pack = frappe.get_doc("Pack", name, for_update=True)
		pack.update({"status": IN_LOAD, "load": load.name})
		pack.flags.tc_packing = True
		pack.save(ignore_permissions=True)
	label = _queue_label(load, machine, program_row, station, started)
	extension.run(
		AFTER_COMPLETE_HOOK,
		{
			"load": load.name,
			"equipment": equipment,
			"program": program_row.name,
			"packs": accepted,
			"sets": [row["set_unit"] for row in rows],
		},
	)
	return {
		"load": load.name,
		"packs": accepted,
		"rejected": rejected,
		"print": label,
		# label preview §4.12 trên kiosk: QR thật của mã mẻ (máy in nhận ZPL riêng)
		"qr_png_b64": base64.b64encode(qr.qr_png(load.name)).decode(),
	}


def _warning(code, title, reason, action):
	return {"code": code, "title": title, "reason": reason, "action": action}


def _queue_label(load, machine, program, station, started):
	"""Tạo Print Job nhãn QR của mẻ tại `station`; trả ``{"print_job", "status", "printer", "zpl", "warning"}``.

	Có máy in hoạt động ở trạm và mẫu `Object label - Sterilization Load` dựng được → ``Queued``. Không có máy in hay
	không dựng được nhãn → ``Waiting`` kèm cảnh báo; mã mẻ vẫn giữ và nhãn in lại được sau.
	"""
	job = {
		"station": station,
		"data": {"label_object": "Sterilization Load", "code": load.name},
		"ref_doctype": "Sterilization Load",
		"ref_name": load.name,
	}
	printer = core_print.object_printer(station)
	zpl = template = warning = None
	if printer is None:
		warning = _warning(
			"NO_PRINTER_AT_STATION",
			_("No printer at this station"),
			_(
				"Station {0} has no active printer. Sterilization load {1} is kept; its label is waiting."
			).format(station, load.name),
			_("Ask R10 to add a printer to this station, then print the load label again."),
		)
	else:
		title = f"{machine.equipment_name} - {program.program_name}"
		subtitle = f"{started:%d/%m/%Y %H:%M}"
		logged = len(frappe.local.message_log)
		try:
			zpl, template = core_print.render_object(
				"Sterilization Load", load.name, title, subtitle, printer=printer, with_template=True
			)
		except frappe.ValidationError as error:
			del frappe.local.message_log[logged:]  # lỗi đã thành cảnh báo, không để msgprint lên kiosk
			warning = _warning(
				"LABEL_RENDER_FAILED",
				_("Label could not be prepared"),
				_("{0} Sterilization load {1} is kept; its label is waiting.").format(error, load.name),
				_("Ask R10 to fix the label template of the sterilization load, then print the label again."),
			)
	if zpl is None:
		name = core_print.create_job(zpl=None, template=None, status="Waiting", **job)
		return {"print_job": name, "status": "Waiting", "printer": None, "zpl": None, "warning": warning}
	name = core_print.create_job(
		zpl=zpl, template=template.name, printer=printer["name"], status="Queued", **job
	)
	return {"print_job": name, "status": "Queued", "printer": printer["name"], "zpl": zpl, "warning": None}


# --- Tra cứu mẻ (FR-M2-09.2) -------------------------------------------------------------------------------


def _load_not_found(raw):
	return _blocked(
		"LOAD_NOT_FOUND",
		_("Sterilization load not found"),
		_("Sterilization load {0} does not exist.").format(raw or "-"),
		_("Scan the QR code on the sterilization load label."),
	)


def _load_doc(load, for_update=False):
	scanned = gs1.parse_scan(load) if isinstance(load, str) else {"type": "unknown", "id": None}
	name = scanned["id"] if scanned["type"] == "load" else None
	if not name or not frappe.db.exists("Sterilization Load", name):
		raise _load_not_found(load if isinstance(load, str) else None)
	return frappe.get_doc("Sterilization Load", name, for_update=for_update)


def _employee(name):
	if not name:
		return None
	return {"name": name, "employee_name": frappe.db.get_value("Employee", name, "employee_name")}


def _pack_rows(doc):
	rows = []
	for row in doc.packs:
		pack = frappe.db.get_value(
			"Pack", row.pack, ["method", "pack_type", "expiry", "status", "set_unit"], as_dict=True
		)
		set_type = frappe.db.get_value("Set Unit", row.set_unit, "set_type") if row.set_unit else None
		rows.append(
			{
				"cycle_id": row.pack,
				"set_id": row.set_unit,
				"set_name": frappe.db.get_value("Instrument Set Type", set_type, "set_type_name")
				if set_type
				else None,
				"method": pack.method if pack else None,
				"pack_type": pack.pack_type if pack else None,
				"expiry": pack.expiry if pack else None,
				"status": pack.status if pack else None,
			}
		)
	return rows


def _describe(doc):
	machine = frappe.db.get_value("Equipment", doc.equipment, list(EQUIPMENT_FIELDS), as_dict=True) or {}
	if machine:
		machine.is_connected = cint(machine.is_connected)
		machine.has_printout = cint(machine.has_printout)
	equipment_type = machine.get("equipment_type") if machine else None
	return {
		"load": doc.name,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"equipment": machine,
		"program": {
			"name": doc.program,
			"program_name": frappe.db.get_value("Process Program", doc.program, "program_name"),
		},
		"indicators": _indicators(equipment_type, doc.requires_bi)
		if equipment_type in STERILIZER_TYPES
		else [],
		"requires_bi": cint(doc.requires_bi),
		"is_priority": cint(doc.is_priority),
		"operator": _employee(doc.operator),
		"load_completed_at": doc.load_completed_at,
		"started_at": doc.started_at,
		"ended_at": doc.ended_at,
		"packs": _pack_rows(doc),
		"data_source": doc.data_source,
		"data_complete": cint(doc.data_complete),
		"needs_review": cint(doc.needs_review),
		"manual_reason": doc.manual_reason,
		"params": frappe.parse_json(doc.params) if doc.params else None,
		"machine_alerts": doc.machine_alerts,
		"machine_report": doc.machine_report,
		"manual_confirmed_by": _employee(doc.manual_confirmed_by),
		"manual_confirmed_at": doc.manual_confirmed_at,
	}


def lookup(raw):
	"""Thẻ tra cứu mẻ từ mã quét `ME-…`: máy, chương trình, chỉ thị, người, giờ, danh sách gói, dữ liệu (FR-M2-09.2).

	Chỉ đọc, mở được ở mọi trạm. Mã không phải mã mẻ → SCAN_INVALID; không có mẻ → LOAD_NOT_FOUND.
	"""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "load":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} is not a sterilization load code.").format(scanned["raw"] or "-"),
			_("Scan the QR code on the sterilization load label."),
		)
	return _describe(_load_doc(scanned["id"]))


# --- Dữ liệu chu trình nhập tay có xác nhận (FR-M2-10, BRU-REP-015) -----------------------------------------


def _check_data_station(station, machine, unload_only=False):
	"""Trạm nhập dữ liệu: trạm nạp, trạm dỡ hoặc trạm đang hoạt động thuộc khu cửa ra của máy (zone_out, rỗng thì zone_in).

	`unload_only`: dỡ mẻ và giải phóng thì trạm chỉ có chức năng nạp không được làm (A-64).
	"""
	row = None
	if isinstance(station, str) and station:
		row = frappe.db.get_value(
			"Zone Station", station, ["is_zone", "is_active", "parent_zone"], as_dict=True
		)
	functions = (UNLOAD_FUNCTION,) if unload_only else LOAD_OR_UNLOAD
	exit_zone = machine.zone_out or machine.zone_in
	if row and not cint(row.is_zone) and cint(row.is_active):
		if zones.station_has_function(station, *functions) or (exit_zone and row.parent_zone == exit_zone):
			return
	raise _blocked(
		"STATION_WRONG_STEP",
		_("Wrong station"),
		_(
			"Station {0} cannot enter data for sterilizer {1}: use a {2} station or a station at the exit door."
		).format(
			station if isinstance(station, str) and station else "-",
			machine.name,
			zones.function_label(functions[-1]),
		),
		_("Enter the cycle data at a {0} station or at a station in zone {1}.").format(
			zones.function_label(functions[-1]), exit_zone or "-"
		),
	)


def _require_open(doc):
	if doc.status not in OPEN_STATUSES or doc.docstatus != 0:
		raise _blocked(
			"LOAD_NOT_OPEN",
			_("Sterilization load is closed"),
			_("Sterilization load {0} is already {1}.").format(
				doc.name, _(doc.status, context="Sterilization Load")
			),
			_("Scan the QR code of a running sterilization load."),
		)


def _scan_kind(doc, raw):
	"""Loại mã quét khi nhập dữ liệu mẻ `doc`: ``equipment`` (đúng máy của mẻ) hoặc ``load`` (đúng mẻ); ngược lại chặn."""
	scanned = gs1.parse_scan(raw) if isinstance(raw, str) else gs1.parse_scan("")
	if scanned["type"] == "equipment":
		if scanned["id"] != doc.equipment:
			raise _blocked(
				"EQUIPMENT_MISMATCH",
				_("Sterilizer does not match"),
				_("Sterilizer {0} does not match sterilizer {1} of load {2}.").format(
					scanned["id"], doc.equipment, doc.name
				),
				_("Scan the QR code of sterilizer {0}.").format(doc.equipment),
			)
		return "equipment"
	if scanned["type"] == "load" and scanned["id"] == doc.name:
		return "load"
	raise _blocked(
		"SCAN_INVALID",
		_("Invalid code"),
		_("Code {0} is not the sterilizer QR code or the code of load {1}.").format(
			scanned["raw"] or "-", doc.name
		),
		_("Scan the QR code of sterilizer {0}, then the QR code of load {1}.").format(
			doc.equipment, doc.name
		),
	)


def _open_for_data(load, equipment_raw, load_raw, station, for_update=False, unload_only=False):
	"""Mẻ còn mở đã kiểm trạm và CẢ HAI mã quét (server không tin kiosk, Q10); trả ``(doc, máy)``."""
	doc = _load_doc(load, for_update=for_update)
	machine = frappe.db.get_value("Equipment", doc.equipment, list(EQUIPMENT_FIELDS), as_dict=True)
	_check_data_station(station, machine, unload_only=unload_only)
	_require_open(doc)
	if _scan_kind(doc, equipment_raw) != "equipment" or _scan_kind(doc, load_raw) != "load":
		raise _blocked(
			"SCAN_INVALID",
			_("Scan both codes"),
			_("Load {0} needs the sterilizer QR code and the load QR code.").format(doc.name),
			_("Scan the QR code of sterilizer {0}, then the QR code of load {1}.").format(
				doc.equipment, doc.name
			),
		)
	return doc, machine


def scan_for_data(load, raw, station):
	"""Kiểm MỘT mã quét khi nhập dữ liệu mẻ `load`: ``{"ok": True, "kind": "equipment" | "load"}``.

	Máy khác máy của mẻ → EQUIPMENT_MISMATCH ngay; mã mẻ khác hoặc mã loại khác → SCAN_INVALID; mẻ đã đóng →
	LOAD_NOT_OPEN; trạm không phải T5/cửa ra → STATION_WRONG_STEP. Không ghi.
	"""
	doc = _load_doc(load)
	machine = frappe.db.get_value("Equipment", doc.equipment, list(EQUIPMENT_FIELDS), as_dict=True)
	_check_data_station(station, machine)
	_require_open(doc)
	return {"ok": True, "kind": _scan_kind(doc, raw)}


def data_context(load, equipment_raw, load_raw, station):
	"""Ngữ cảnh nhập dữ liệu sau khi đã quét QR máy và QR mẻ: `lookup` + ``parameter_schema`` của chương trình."""
	doc, _machine = _open_for_data(load, equipment_raw, load_raw, station)
	return {**_describe(doc), "parameter_schema": _parameters(doc.program)}


def _number(value):
	if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
		return None
	try:
		return float(str(value).strip().replace(",", "."))
	except ValueError:
		return None


def _outside(value, low, high):
	"""Ngoài dải theo `param_schema`: giới hạn bằng 0 là không đặt, dải một phía hợp lệ."""
	low, high = flt(low), flt(high)
	return bool((low and value < low) or (high and value > high))


def _datetime_or_none(value):
	if not value:
		return None
	try:
		return get_datetime(value).replace(tzinfo=None)
	except Exception:
		return None


def _incomplete(doc, missing):
	return _blocked(
		"DATA_INCOMPLETE",
		_("Cycle data is incomplete"),
		_("Sterilization load {0} has no complete, confirmed cycle data, so nothing was saved.").format(
			doc.name
		),
		_("Enter the cycle data from the sterilizer screen or printout, confirm it and scan your card."),
		items=missing,
	)


def save_manual_data(
	load,
	equipment_raw,
	load_raw,
	values,
	started_at,
	ended_at,
	machine_alerts,
	machine_report,
	reason,
	confirmed,
	card,
	client_ts,
	employee=None,
	station=None,
):
	"""Lưu dữ liệu chu trình nhập tay của mẻ còn mở (nguồn `Manual`); trả ``{"data_complete", "needs_review", "status", "params"}``.

	`values` là ``[{"parameter_name", "value"}]`` theo chương trình. **Không lưu gì** (DATA_INCOMPLETE, FR-M2-10.1) khi
	thiếu tham số `required`, giờ kết thúc (hoặc trước giờ bắt đầu), ảnh bản in (máy có bản in, FR-M2-10.2), lý do
	(máy kết nối được mà nhập tay, FR-M2-10.4), chưa tick xác nhận hoặc chưa quét thẻ. Thẻ quét phải là thẻ của
	`employee` (Employee của phiên) — khác → CARD_MISMATCH (A-16, Q11). Giá trị ngoài dải vẫn lưu, đặt
	``needs_review`` (FR-M2-10.3). Đủ dữ liệu → ``status = Cycle Complete``. Sửa lại được khi mẻ còn mở.
	"""
	client_time.check_skew(client_ts)
	doc, machine = _open_for_data(load, equipment_raw, load_raw, station, for_update=True)
	given = {}
	for row in values or []:
		if isinstance(row, dict) and row.get("parameter_name"):
			given[row["parameter_name"]] = row.get("value")
	parameters, missing, review = [], [], False
	for schema in _parameters(doc.program):
		value = _number(given.get(schema.parameter_name))
		if value is None:
			if cint(schema.required):
				missing.append(schema.parameter_name)
			continue
		outside = _outside(value, schema.min_value, schema.max_value)
		review = review or outside
		parameters.append(
			{
				"parameter_name": schema.parameter_name,
				"unit": schema.unit,
				"value": value,
				"min_value": flt(schema.min_value),
				"max_value": flt(schema.max_value),
				"outside_range": outside,
			}
		)
	started = _datetime_or_none(started_at) or get_datetime(doc.started_at)
	ended = _datetime_or_none(ended_at)
	if not ended or ended < started:
		missing.append(MISSING_ENDED_AT)
	if cint(machine.has_printout) and not machine_report:
		missing.append(MISSING_PRINTOUT)
	if cint(machine.is_connected) and not (reason or "").strip():
		missing.append(MISSING_REASON)
	if not confirmed:
		missing.append(MISSING_CONFIRMATION)
	if not card:
		missing.append(MISSING_CARD)
	elif not employee or _card_of(employee) != _clean_card(card):
		raise _blocked(
			"CARD_MISMATCH",
			_("Card does not match"),
			_("The scanned card is not the card of the employee signed in at this station."),
			_("Scan your own card to confirm, or sign in again."),
		)
	if missing:
		raise _incomplete(doc, missing)
	doc.update(
		{
			"params": frappe.as_json(parameters),
			"machine_alerts": frappe.as_json({"text": machine_alerts}) if machine_alerts else None,
			"machine_report": machine_report or None,
			"started_at": started,
			"ended_at": ended,
			"data_source": "Manual",
			"data_complete": 1,
			"needs_review": 1 if review else 0,
			"manual_reason": (reason or "").strip() or None,
			"manual_confirmed_by": employee,
			"manual_confirmed_at": _system_time(client_ts),
			"status": CYCLE_COMPLETE,
		}
	)
	doc.flags.tc_sterilizing = True
	doc.save(ignore_permissions=True)
	return {
		"data_complete": doc.data_complete,
		"needs_review": doc.needs_review,
		"status": doc.status,
		"params": parameters,
	}


def _clean_card(card):
	return station_auth.normalize_card_id(gs1.clean_scan(card)) if isinstance(card, str) else ""


def _card_of(employee):
	return station_auth.normalize_card_id(frappe.db.get_value("Employee", employee, "tc_card_id"))
