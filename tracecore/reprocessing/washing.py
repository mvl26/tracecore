"""Lô rửa tại T2 (M2, FEAT-021, UC-06): quy tắc máy, nạp bộ, hóa chất; dịch vụ nạp, dỡ và kết luận lô.

- Quy tắc (Task 2): `check_equipment_ready`, `scan_machine`, `admit_set`, `suggest_chemical_lots`,
  `check_chemical_lot`, `redo_queue`.

M2 không import `tracecore.equipment`/`tracecore.inventory` (lint R1): máy, chương trình, lô hóa chất đọc bằng tên
DocType, như `packing.resolve_ci_batch`. Trạng thái Set Unit chỉ đổi qua `core.step_gate`; lô chỉ đổi ở đây bằng cờ
``flags.tc_washing`` của Wash Batch. Từ chối nghiệp vụ là `BlockedError` (mã HTTP ở `core.errors`).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, getdate, now_datetime

from tracecore.core import gs1, step_gate
from tracecore.core.errors import Block, BlockedError

STEP = "T2"
WASH_EQUIPMENT_TYPES = ("Washer-Disinfector", "Ultrasonic Cleaner")
RUNNING = "Running"
CHEMICAL_GROUP = "Chemical"  # Item.tc_item_group_cssd của hóa chất rửa (FEAT-041)
EQUIPMENT_FIELDS = (
	"name equipment_name equipment_type status zone_in zone_out is_connected has_printout".split()
)


def _blocked(code, title, reason, action, items=None):
	return BlockedError(Block(code, title, reason, action, items=items))


def _today():
	"""Ngày hôm nay theo giờ hệ thống (Asia/Ho_Chi_Minh), không theo UTC."""
	return getdate(now_datetime())


# --- Máy rửa (FR-M2-03.4, UC-06 E1) ---------------------------------------------------------------


def check_equipment_ready(equipment):
	"""Block nếu `equipment` không dùng được để nạp lô rửa, ngược lại None.

	Thứ tự: không có máy → EQUIPMENT_NOT_FOUND; không phải máy rửa → EQUIPMENT_NOT_WASHER; trạng thái khác Sẵn
	sàng → EQUIPMENT_NOT_READY. Test hằng ngày và kiểm định (FEAT-040) thêm điều kiện ở đây.
	"""
	row = frappe.db.get_value("Equipment", equipment, ["equipment_type", "status"], as_dict=True)
	if not row:
		return Block(
			"EQUIPMENT_NOT_FOUND",
			_("Equipment not found"),
			_("Equipment {0} does not exist.").format(equipment or "-"),
			_("Scan the QR code on the washer."),
		)
	if row.equipment_type not in WASH_EQUIPMENT_TYPES:
		return Block(
			"EQUIPMENT_NOT_WASHER",
			_("Not a washer"),
			_("Equipment {0} is a {1}, not a washer-disinfector or ultrasonic cleaner.").format(
				equipment, _(row.equipment_type)
			),
			_("Scan the QR code of a washer."),
		)
	if row.status != "Ready":
		return Block(
			"EQUIPMENT_NOT_READY",
			_("Washer is not ready"),
			_("Equipment {0} is {1}.").format(equipment, _(row.status, context="Equipment")),
			_("Use another washer, or call R02 to check the daily test and the inspection."),
		)
	return None


def _parameters(program):
	return frappe.get_all(
		"Program Parameter",
		filters={"parent": program, "parenttype": "Process Program"},
		fields=["parameter_name", "unit", "min_value", "max_value", "required"],
		order_by="idx asc",
	)


def scan_machine(raw):
	"""Mở lô rửa từ mã QR máy: máy, chương trình đang dùng của máy và lô hóa chất gợi ý (FR-M2-03.1, FR-M2-03.4/.5).

	``{"equipment": {...}, "programs": [...], "chemical_lots": [...]}``. Mã không phải máy rửa → SCAN_INVALID;
	máy không dùng được → `check_equipment_ready`.
	"""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "equipment":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} is not a washer QR code.").format(scanned["raw"] or "-"),
			_("Scan the QR code on the washer."),
		)
	block = check_equipment_ready(scanned["id"])
	if block:
		raise BlockedError(block)
	equipment = frappe.db.get_value("Equipment", scanned["id"], list(EQUIPMENT_FIELDS), as_dict=True)
	equipment.is_connected = cint(equipment.is_connected)
	equipment.has_printout = cint(equipment.has_printout)
	programs, lots, seen = [], [], set()
	for row in frappe.get_all(
		"Process Program",
		filters={"equipment": equipment.name, "is_active": 1},
		fields=["name", "program_name", "requires_bi", "chemical"],
		order_by="program_name asc",
	):
		programs.append(
			{
				"program_code": row.name,
				"program_name": row.program_name,
				"requires_bi": cint(row.requires_bi),
				"chemical": row.chemical,
				"parameters": _parameters(row.name),
			}
		)
		if row.chemical and row.chemical not in seen:
			seen.add(row.chemical)
			lots.extend(suggest_chemical_lots(row.chemical))
	return {"equipment": equipment, "programs": programs, "chemical_lots": lots}


# --- Nạp bộ vào lô (FR-M2-03.6, FR-M2-25) -----------------------------------------------------------


def _set_not_found(raw):
	return _blocked(
		"SET_NOT_FOUND",
		_("Set not found"),
		_("Set ID {0} does not exist in TraceCore.").format(raw or "-"),
		_("Check the set tag or call R02."),
	)


def _t2_result(set_unit):
	"""Kết quả cổng T2 của chu trình hiện hành (`Pass`/`Fail`/`Pending`)."""
	for gate in step_gate.gates(set_unit):
		if gate["step"] == STEP:
			return gate["result"]
	return step_gate.PENDING


def _running_batch_of(set_unit):
	"""Tên lô rửa đang chạy chứa `set_unit`, hoặc None."""
	rows = frappe.db.sql(
		"""select batch.name from `tabWash Batch Set Unit` row
		join `tabWash Batch` batch on batch.name = row.parent
		where row.set_unit = %s and batch.status = %s and batch.docstatus = 0
		limit 1""",
		(set_unit, RUNNING),
	)
	return rows[0][0] if rows else None


def admit_set(raw, equipment, queued=None, for_update=False):
	"""Kiểm một Set ID quét vào lô rửa trên máy `equipment`; không ghi.

	Trả ``{"set_id", "set_name", "set_type", "duplicate", "gates"}``. Bộ đã có trong `queued` thì
	``duplicate = True`` và không phải lỗi (FR-M2-03.6 không cấm quét lặp; kiosk chỉ báo đã có). Từ chối theo thứ
	tự: máy hợp lệ → mã là Set ID → bộ tồn tại → cổng T1 Đạt và trạng thái hợp trạm (`step_gate.check`) → chưa Đạt
	T2 trong chu trình (STEP_ALREADY_PASSED) → không ở lô khác (SET_IN_OTHER_BATCH).
	"""
	block = check_equipment_ready(equipment)
	if block:
		raise BlockedError(block)
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "set":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} is not a set ID.").format(scanned["raw"] or "-"),
			_("Scan the Set ID on the tray or tag."),
		)
	set_id = scanned["id"]
	set_type = frappe.db.get_value("Set Unit", set_id, "set_type")
	if not set_type:
		raise _set_not_found(scanned["raw"])
	if set_id in set(queued or []):
		return _admitted(set_id, set_type, duplicate=True)
	block = step_gate.check(set_id, STEP, for_update)
	if block:
		raise BlockedError(block)
	if _t2_result(set_id) == "Pass":
		raise _blocked(
			"STEP_ALREADY_PASSED",
			_("Set already washed"),
			_("Set {0} has already passed the wash step in this cycle.").format(set_id),
			_("Take the set to the next step."),
		)
	other = _running_batch_of(set_id)
	if other:
		raise _blocked(
			"SET_IN_OTHER_BATCH",
			_("Set is in another wash batch"),
			_("Set {0} is in wash batch {1}, which is still running.").format(set_id, other),
			_("Unload batch {0} first, or take the set out of the washer.").format(other),
		)
	return _admitted(set_id, set_type, duplicate=False)


def _admitted(set_id, set_type, duplicate):
	started = cint(frappe.db.get_value("Set Unit", set_id, "current_cycle_no")) > 0
	return {
		"set_id": set_id,
		"set_name": frappe.db.get_value("Instrument Set Type", set_type, "set_type_name"),
		"set_type": set_type,
		"duplicate": duplicate,
		"gates": step_gate.gates(set_id) if started else [],
	}


def redo_queue():
	"""Bộ chờ rửa lại: cổng T2 `Fail` trong chu trình hiện hành, kèm số lần xử lý lại (FR-M2-25.2, Q16)."""
	rows = frappe.db.sql(
		"""select gate.set_unit, gate.redo_count, unit.set_type
		from `tabStep Gate Result` gate
		join `tabSet Unit` unit on unit.name = gate.set_unit and unit.current_cycle_no = gate.cycle_no
		where gate.step = %s and gate.result = 'Fail' and unit.status = 'Reprocess'
		order by gate.set_unit asc""",
		(STEP,),
	)
	return [
		{
			"set_id": set_unit,
			"set_name": frappe.db.get_value("Instrument Set Type", set_type, "set_type_name"),
			"redo_count": cint(redo_count),
		}
		for set_unit, redo_count, set_type in rows
	]


# --- Hóa chất (FR-M2-03.5, BRU-INV-001) ---------------------------------------------------------------


def suggest_chemical_lots(item):
	"""Lô còn hạn và còn tồn của hóa chất `item`, hạn gần nhất trước (FEFO).

	Mỗi lô ``{"item", "batch_no", "expiry_date", "qty", "uom"}``; lô hết hạn trước hôm nay, đã ngừng hoặc hết tồn
	bị loại (lô hết hạn đúng hôm nay vẫn dùng được).
	"""
	uom = frappe.db.get_value("Item", item, "stock_uom")
	rows = frappe.get_all(
		"Batch",
		filters={
			"item": item,
			"disabled": 0,
			"expiry_date": [">=", _today()],
			"batch_qty": [">", 0],
		},
		fields=["name", "expiry_date", "batch_qty"],
		order_by="expiry_date asc, name asc",
	)
	return [
		{
			"item": item,
			"batch_no": row.name,
			"expiry_date": row.expiry_date,
			"qty": flt(row.batch_qty),
			"uom": uom,
		}
		for row in rows
	]


def check_chemical_lot(item, batch_no):
	"""Block nếu `batch_no` không dùng được làm lô hóa chất của `item`, ngược lại None."""
	batch = frappe.db.get_value("Batch", batch_no, ["name", "item", "expiry_date", "disabled"], as_dict=True)
	group = frappe.db.get_value("Item", item, "tc_item_group_cssd") if item else None
	if not batch or batch.item != item or group != CHEMICAL_GROUP:
		return _invalid_chemical(_("Lot {0} is not a lot of chemical {1}.").format(batch_no or "-", item or "-"))
	if cint(batch.disabled):
		return _invalid_chemical(_("Lot {0} has been disabled.").format(batch.name))
	if not batch.expiry_date:
		return _invalid_chemical(_("Lot {0} has no expiry date, so it cannot be checked.").format(batch.name))
	expiry = getdate(batch.expiry_date)
	if expiry < _today():
		return Block(
			"CHEMICAL_LOT_EXPIRED",
			_("Chemical lot has expired"),
			_("Lot {0} expired on {1}.").format(batch.name, formatdate(expiry)),
			_("Choose another lot that is still valid."),
		)
	return None


def _invalid_chemical(reason):
	return Block(
		"CHEMICAL_LOT_INVALID",
		_("Chemical lot is not valid"),
		reason,
		_("Choose a lot of the chemical that the wash program uses."),
	)
