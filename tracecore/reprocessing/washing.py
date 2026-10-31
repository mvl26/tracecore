"""Lô rửa tại T2 (M2, FEAT-021, UC-06): quy tắc máy, nạp bộ, hóa chất; dịch vụ nạp, dỡ và kết luận lô.

- Quy tắc: `check_equipment_ready`, `scan_machine`, `admit_set`, `suggest_chemical_lots`, `check_chemical_lot`,
  `redo_queue`, `waiting_sets`.
- Dịch vụ trạm T2: `start` (Hoàn thành nạp: sinh mã lô, gắn bộ, in nhãn QR); `lookup` (tra cứu lô);
  `scan_unload`, `unload_context` (dỡ lô: QR máy + QR lô), `save_manual_data` (dữ liệu chu trình nhập tay có xác
  nhận), `set_result` (kết luận Đạt/Không đạt áp cho mọi bộ, đóng lô).

M2 không import `tracecore.equipment`/`tracecore.inventory` (lint R1): máy, chương trình, lô hóa chất đọc bằng tên
DocType, như `packing.resolve_ci_batch`. Trạng thái Set Unit chỉ đổi qua `core.step_gate`; lô chỉ đổi ở đây bằng cờ
``flags.tc_washing`` của Wash Batch. Từ chối nghiệp vụ là `BlockedError` (mã HTTP ở `core.errors`).
"""

import base64
import contextlib
from datetime import timezone
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, get_datetime, getdate, now_datetime
from frappe.utils.data import get_system_timezone

from tracecore.core import audit, client_time, extension, gs1, qr, station_auth, step_gate
from tracecore.core import print as core_print
from tracecore.core.errors import Block, BlockedError

STEP = "T2"
SAVEPOINT = "tc_wash_start"
RESULT_SAVEPOINT = "tc_wash_result"
WASH_EQUIPMENT_TYPES = ("Washer-Disinfector", "Ultrasonic Cleaner")
EQUIPMENT_CHECKS_HOOK = "tracecore_wash_equipment_checks"
RUNNING = "Running"
RESULTS = ("Pass", "Fail")
CLOSED_STATUS = {"Pass": "Passed", "Fail": "Failed"}
REVIEWER_ROLE = "TC R02"  # xác nhận Đạt cho máy cũ không kết nối, không bản in (Q7)
AFTER_COMPLETE_HOOK = "tracecore_after_wash_complete"
AFTER_FAILED_HOOK = "tracecore_after_wash_failed"
# mục thiếu của dữ liệu chu trình ngoài tên tham số (kiosk dịch sang chữ)
MISSING_ENDED_AT = "ended_at"
MISSING_PRINTOUT = "printout"
MISSING_CONFIRMATION = "confirmation"
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
	for block in extension.run(EQUIPMENT_CHECKS_HOOK, equipment):
		if isinstance(block, Block):
			return block
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


def _running_batch_of(set_unit, for_update=False):
	"""Tên lô rửa đang chạy chứa `set_unit`, hoặc None.

	for_update: đọc có khóa để thấy lô vừa được request khác commit (snapshot REPEATABLE READ có thể cũ, xem
	docstring của `core.step_gate`); nơi gọi đã khóa Set Unit trước nên chỉ một request vào được tại đây.
	"""
	rows = frappe.db.sql(_RUNNING_BATCH_LOCKED_SQL if for_update else _RUNNING_BATCH_SQL, (set_unit, RUNNING))
	return rows[0][0] if rows else None


_RUNNING_BATCH_SQL = """select batch.name from `tabWash Batch Set Unit` row
	join `tabWash Batch` batch on batch.name = row.parent
	where row.set_unit = %s and batch.status = %s and batch.docstatus = 0
	limit 1"""
_RUNNING_BATCH_LOCKED_SQL = _RUNNING_BATCH_SQL + " for update"


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
	# tra không phân biệt hoa thường (collation) → dùng Set ID đã lưu để so quét lặp và trả về kiosk
	found = frappe.db.get_value("Set Unit", scanned["id"], ["name", "set_type"])
	if not found or not found[1]:
		raise _set_not_found(scanned["raw"])
	set_id, set_type = found
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
	other = _running_batch_of(set_id, for_update)
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


def waiting_sets():
	"""Bộ chờ rửa (A-66, UC-06 A4): T1 Đạt trong chu trình hiện hành, hợp trạm T2, cổng T2 chưa có kết quả, không ở lô đang chạy.

	Cùng điều kiện nhận của `admit_set`; bộ T2 Không đạt nằm ở `redo_queue`. Chỉ để hiển thị, KTV vẫn quét từng bộ.
	"""
	return frappe.db.sql(
		"""select unit.name as set_id, set_type.set_type_name as set_name, department.department_name
		from `tabSet Unit` unit
		join `tabStep Gate Result` t1 on t1.set_unit = unit.name and t1.cycle_no = unit.current_cycle_no
			and t1.step = 'T1' and t1.result = 'Pass'
		left join `tabStep Gate Result` t2 on t2.set_unit = unit.name and t2.cycle_no = unit.current_cycle_no
			and t2.step = %(step)s
		left join `tabInstrument Set Type` set_type on set_type.name = unit.set_type
		left join `tabDepartment` department on department.name = unit.department
		where unit.status in %(statuses)s and ifnull(t2.result, %(pending)s) = %(pending)s
			and not exists (
				select 1 from `tabWash Batch Set Unit` row
				join `tabWash Batch` batch on batch.name = row.parent
				where row.set_unit = unit.name and batch.status = %(running)s and batch.docstatus = 0
			)
		order by unit.name asc""",
		{
			"step": STEP,
			"statuses": step_gate.STATION_STATUSES[STEP],
			"pending": step_gate.PENDING,
			"running": RUNNING,
		},
		as_dict=True,
	)


def running_batches():
	"""Lô đang chạy (chưa dỡ) để màn T2 hiện thẻ "Lô đang chạy" (SCR-06): máy, chương trình, bộ, dữ liệu."""
	rows = frappe.get_all(
		"Wash Batch",
		filters={"status": RUNNING, "docstatus": 0},
		fields=["name", "equipment", "program", "load_completed_at", "data_complete", "needs_review"],
		order_by="load_completed_at asc, name asc",
	)
	out = []
	for row in rows:
		sets = frappe.get_all(
			"Wash Batch Set Unit",
			filters={"parent": row.name, "parenttype": "Wash Batch"},
			pluck="set_unit",
			order_by="idx asc",
		)
		out.append(
			{
				"batch": row.name,
				"equipment": row.equipment,
				"equipment_name": frappe.db.get_value("Equipment", row.equipment, "equipment_name"),
				"program": row.program,
				"program_name": frappe.db.get_value("Process Program", row.program, "program_name"),
				"load_completed_at": row.load_completed_at,
				"data_complete": cint(row.data_complete),
				"needs_review": cint(row.needs_review),
				"sets": sets,
			}
		)
	return out


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
		return _invalid_chemical(
			_("Lot {0} is not a lot of chemical {1}.").format(batch_no or "-", item or "-")
		)
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


# --- Hoàn thành nạp (FR-M2-03.2, FR-M2-24.1, BRU-REP-016) -------------------------------------------------


def _system_time(client_ts):
	"""`client_ts` UTC không múi giờ → giờ hệ thống (Asia/Ho_Chi_Minh) không múi giờ (ADR-003)."""
	utc = get_datetime(client_ts).replace(tzinfo=timezone.utc)
	return utc.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def _program(equipment, program):
	"""Chương trình `program` của máy `equipment` còn dùng, hoặc PROGRAM_INVALID."""
	row = frappe.db.get_value(
		"Process Program",
		program,
		["name", "program_name", "equipment", "is_active", "chemical"],
		as_dict=True,
	)
	if not row or row.equipment != equipment or not cint(row.is_active):
		raise _blocked(
			"PROGRAM_INVALID",
			_("Program is not valid"),
			_("Program {0} is not an active program of equipment {1}.").format(program or "-", equipment),
			_("Choose a program from the list of this washer."),
		)
	return row


def _chemical_rows(program, chemicals):
	"""Dòng hóa chất đã kiểm của lô (Q23): lô còn hạn, đúng hóa chất của chương trình, ít nhất một lô nếu có khai."""
	rows = []
	for entry in chemicals or []:
		item, lot = entry.get("item"), entry.get("lot")
		if program.chemical and item != program.chemical:
			raise BlockedError(
				_invalid_chemical(
					_("Program {0} uses chemical {1}, not {2}.").format(
						program.name, program.chemical, item or "-"
					)
				)
			)
		block = check_chemical_lot(item, lot)
		if block:
			raise BlockedError(block)
		rows.append({"item": item, "lot": lot, "qty": flt(entry.get("qty"))})
	if program.chemical and not rows:
		raise BlockedError(
			_invalid_chemical(
				_("Program {0} needs a lot of chemical {1}.").format(program.name, program.chemical)
			)
		)
	return rows


def _admit_all(sets, equipment):
	"""``(bộ nhận được, bộ bị loại)`` cho danh sách quét `sets`; bộ bị loại là ``{"set_id", "code", "reason"}``.

	Khóa các Set Unit theo thứ tự tên rồi kiểm lại từng bộ bằng đọc có khóa: hai kiosk cùng nạp một bộ thì chỉ một
	nơi giữ được, nơi kia thấy SET_IN_OTHER_BATCH. Quét lặp cùng bộ chỉ tính một lần.
	"""
	scanned = [(raw, gs1.parse_scan(raw)) for raw in sets or []]
	for set_id in sorted({s["id"] for _raw, s in scanned if s["type"] == "set"}):
		frappe.db.get_value("Set Unit", set_id, "name", for_update=True)
	accepted, rejected = [], []
	for raw, parsed in scanned:
		try:
			admitted = admit_set(raw, equipment, accepted, for_update=True)
		except BlockedError as error:
			rejected.append(
				{
					"set_id": parsed["id"] or parsed["raw"],
					"code": error.block.code,
					"reason": error.block.reason,
				}
			)
			continue
		if not admitted["duplicate"]:
			accepted.append(admitted["set_id"])
	return accepted, rejected


def start(equipment, program, sets, chemicals, station, client_ts, operator):
	"""Hoàn thành nạp: sinh mã lô `LR-YYMMDD-NN` cho các bộ quét vào máy, ghi lô `Running` và xếp lệnh in nhãn QR.

	`client_ts` là kết quả `parse_client_ts` (UTC); giờ nạp = giờ hệ thống của nó, lệch giờ server quá
	`client_time.max_skew_seconds()` → ClientTimestampError trước khi ghi gì. `operator` là Employee đăng nhập thẻ.
	Máy phải Sẵn sàng, chương trình thuộc máy, hóa chất còn hạn (cả lô bị từ chối nếu sai). Bộ nào không còn hợp lệ
	(bị lô khác lấy, đã qua T2…) vào `rejected` mà không dừng lô; không còn bộ nào → BATCH_EMPTY. Mọi lỗi hoàn tác về
	savepoint rồi ném lại: không còn lô, dòng Code Registry hay số series nào. In không bao giờ làm mất mã lô.

	Trả ``{"batch", "sets", "rejected", "print": {"print_job", "status", "printer", "zpl", "warning"}}``.
	"""
	client_time.check_skew(client_ts)
	frappe.db.savepoint(SAVEPOINT)
	try:
		return _start(equipment, program, sets, chemicals, station, client_ts, operator)
	except Exception:
		# Sau deadlock InnoDB đã hoàn tác cả transaction (savepoint không còn): giữ lỗi gốc, bỏ lỗi rollback
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _start(equipment, program, sets, chemicals, station, client_ts, operator):
	block = check_equipment_ready(equipment)
	if block:
		raise BlockedError(block)
	machine = frappe.db.get_value("Equipment", equipment, ["equipment_name", "equipment_type"], as_dict=True)
	program = _program(equipment, program)
	chemical_rows = _chemical_rows(program, chemicals)
	accepted, rejected = _admit_all(sets, equipment)
	if not accepted:
		raise _blocked(
			"BATCH_EMPTY",
			_("No set can be loaded"),
			_("None of the scanned sets can go into a wash batch on {0}.").format(equipment),
			_("Scan sets that have passed receiving, then complete loading again."),
			items=rejected or None,
		)
	started = _system_time(client_ts)
	batch = frappe.get_doc(
		{
			"doctype": "Wash Batch",
			"batch_type": "Ultrasonic" if machine.equipment_type == "Ultrasonic Cleaner" else "Machine",
			"equipment": equipment,
			"program": program.name,
			"operator": operator,
			"status": RUNNING,
			"loaded_by_scan": 1,
			"load_completed_at": started,
			"started_at": started,
			"set_units": [{"set_unit": set_id, "added_at": started} for set_id in accepted],
			"chemicals": chemical_rows,
		}
	)
	batch.flags.tc_washing = True
	batch.insert(ignore_permissions=True)
	label = _queue_label(batch, machine, program, station, started)
	return {
		"batch": batch.name,
		"sets": accepted,
		"rejected": rejected,
		"print": label,
		# label preview §4.12 trên kiosk: QR thật của mã lô (máy in nhận ZPL riêng)
		"qr_png_b64": base64.b64encode(qr.qr_png(batch.name)).decode(),
	}


def _warning(code, title, reason, action):
	return {"code": code, "title": title, "reason": reason, "action": action}


def _queue_label(batch, machine, program, station, started):
	"""Tạo Print Job nhãn QR của lô tại `station`; trả ``{"print_job", "status", "printer", "zpl", "warning"}``.

	Có máy in hoạt động ở trạm và mẫu `Object label - Wash Batch` dựng được → ``Queued``. Không có máy in hay không
	dựng được nhãn → ``Waiting`` kèm cảnh báo; mã lô vẫn giữ và nhãn in lại được sau.
	"""
	job = {
		"station": station,
		"data": {"label_object": "Wash Batch", "code": batch.name},
		"ref_doctype": "Wash Batch",
		"ref_name": batch.name,
	}
	printer = core_print.object_printer(station)
	zpl = template = warning = None
	if printer is None:
		warning = _warning(
			"NO_PRINTER_AT_STATION",
			_("No printer at this station"),
			_("Station {0} has no active printer. Wash batch {1} is kept; its label is waiting.").format(
				station, batch.name
			),
			_("Ask R10 to add a printer to this station, then print the batch label again."),
		)
	else:
		title = f"{machine.equipment_name} - {program.program_name}"
		subtitle = f"{started:%d/%m/%Y %H:%M}"
		logged = len(frappe.local.message_log)
		try:
			zpl, template = core_print.render_object(
				"Wash Batch", batch.name, title, subtitle, printer=printer, with_template=True
			)
		except frappe.ValidationError as error:
			del frappe.local.message_log[logged:]  # lỗi đã thành cảnh báo, không để msgprint lên kiosk
			warning = _warning(
				"LABEL_RENDER_FAILED",
				_("Label could not be prepared"),
				_("{0} Wash batch {1} is kept; its label is waiting.").format(error, batch.name),
				_("Ask R10 to fix the label template of the wash batch, then print the label again."),
			)
	if zpl is None:
		name = core_print.create_job(zpl=None, template=None, status="Waiting", **job)
		return {"print_job": name, "status": "Waiting", "printer": None, "zpl": None, "warning": warning}
	name = core_print.create_job(
		zpl=zpl, template=template.name, printer=printer["name"], status="Queued", **job
	)
	return {"print_job": name, "status": "Queued", "printer": printer["name"], "zpl": zpl, "warning": None}


# --- Tra cứu lô (FR-M2-03.3) ------------------------------------------------------------------------------


def _batch_not_found(raw):
	return _blocked(
		"WASH_BATCH_NOT_FOUND",
		_("Wash batch not found"),
		_("Wash batch {0} does not exist.").format(raw or "-"),
		_("Scan the QR code on the wash batch label."),
	)


def _batch_name(batch):
	"""Tên lô từ mã quét hoặc tên đã chuẩn hóa (bỏ tiền tố AIM, khoảng trắng, CR/LF)."""
	scanned = gs1.parse_scan(batch) if isinstance(batch, str) else {"type": "unknown", "id": None}
	return scanned["id"] if scanned["type"] == "wash_batch" else None


def _batch_doc(batch, for_update=False):
	name = _batch_name(batch)
	if not name or not frappe.db.exists("Wash Batch", name):
		raise _batch_not_found(batch if isinstance(batch, str) else None)
	return frappe.get_doc("Wash Batch", name, for_update=for_update)


def _employee(name):
	if not name:
		return None
	return {"name": name, "employee_name": frappe.db.get_value("Employee", name, "employee_name")}


def _set_rows(doc):
	rows = []
	for row in doc.set_units:
		unit = frappe.db.get_value(
			"Set Unit", row.set_unit, ["set_type", "status", "current_cycle_no"], as_dict=True
		)
		redo = 0
		if unit and cint(unit.current_cycle_no):
			redo = next(g["redo_count"] for g in step_gate.gates(row.set_unit) if g["step"] == STEP)
		rows.append(
			{
				"set_id": row.set_unit,
				"set_name": frappe.db.get_value("Instrument Set Type", unit.set_type, "set_type_name")
				if unit
				else None,
				"status": unit.status if unit else None,
				"redo_count": redo,
			}
		)
	return rows


def _describe(doc):
	machine = frappe.db.get_value("Equipment", doc.equipment, list(EQUIPMENT_FIELDS), as_dict=True) or {}
	if machine:
		machine.is_connected = cint(machine.is_connected)
		machine.has_printout = cint(machine.has_printout)
	return {
		"batch": doc.name,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"batch_type": doc.batch_type,
		"equipment": machine,
		"program": {
			"name": doc.program,
			"program_name": frappe.db.get_value("Process Program", doc.program, "program_name"),
		},
		"operator": _employee(doc.operator),
		"load_completed_at": doc.load_completed_at,
		"started_at": doc.started_at,
		"ended_at": doc.ended_at,
		"sets": _set_rows(doc),
		"chemicals": [
			{
				"item": row.item,
				"lot": row.lot,
				"qty": flt(row.qty),
				"expiry_date": frappe.db.get_value("Batch", row.lot, "expiry_date"),
			}
			for row in doc.chemicals
		],
		"data_source": doc.data_source,
		"data_complete": cint(doc.data_complete),
		"needs_review": cint(doc.needs_review),
		"machine_data": frappe.parse_json(doc.machine_data) if doc.machine_data else None,
		"machine_files": doc.machine_files,
		"manual_confirmed_by": _employee(doc.manual_confirmed_by),
		"manual_confirmed_at": doc.manual_confirmed_at,
		"cycle_result": doc.cycle_result,
		"clean_test_result": doc.clean_test_result,
		"unloaded_at": doc.unload_scan_at,
		"reviewer": doc.reviewer,
		"result_note": doc.result_note,
		"nc_pending": cint(doc.nc_pending),
	}


def lookup(raw):
	"""Thẻ tra cứu lô rửa từ mã quét `LR-…` (máy, chương trình, giờ, người nạp, bộ, hóa chất, dữ liệu, kết quả).

	Chỉ đọc, mở được ở mọi trạm (FR-M2-03.3). Mã không phải mã lô → SCAN_INVALID; không có lô → WASH_BATCH_NOT_FOUND.
	"""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "wash_batch":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} is not a wash batch code.").format(scanned["raw"] or "-"),
			_("Scan the QR code on the wash batch label."),
		)
	return _describe(_batch_doc(scanned["id"]))


# --- Dỡ lô (FR-M2-04.1/.2/.7, BRU-REP-016) ------------------------------------------------------------------


def _check_unload_station(station, machine):
	"""Trạm dỡ: trạm T2, hoặc trạm đang hoạt động thuộc khu cửa ra của máy (zone_out, rỗng thì zone_in) — Q5."""
	row = None
	if isinstance(station, str) and station:
		row = frappe.db.get_value(
			"Zone Station", station, ["is_zone", "is_active", "station_step", "parent_zone"], as_dict=True
		)
	exit_zone = machine.zone_out or machine.zone_in
	if row and not cint(row.is_zone) and cint(row.is_active):
		if row.station_step == STEP or (exit_zone and row.parent_zone == exit_zone):
			return
	raise _blocked(
		"STATION_WRONG_STEP",
		_("Wrong station"),
		_("Station {0} cannot unload washer {1}: use a T2 station or a station at the exit door.").format(
			station if isinstance(station, str) and station else "-", machine.name
		),
		_("Unload the batch at a T2 station or at a station in zone {0}.").format(exit_zone or "-"),
	)


def _require_running(doc):
	if doc.status != RUNNING or doc.docstatus != 0:
		raise _blocked(
			"BATCH_NOT_RUNNING",
			_("Wash batch is closed"),
			_("Wash batch {0} is already {1}.").format(doc.name, _(doc.status, context="Wash Batch")),
			_("Scan the QR code of a running wash batch."),
		)


def _scan_kind(doc, raw):
	"""Loại mã quét khi dỡ lô `doc`: ``equipment`` (đúng máy của lô) hoặc ``wash_batch`` (đúng lô); ngược lại chặn."""
	scanned = gs1.parse_scan(raw) if isinstance(raw, str) else gs1.parse_scan("")
	if scanned["type"] == "equipment":
		if scanned["id"] != doc.equipment:
			raise _blocked(
				"EQUIPMENT_MISMATCH",
				_("Washer does not match"),
				_("Washer {0} does not match washer {1} of batch {2}.").format(
					scanned["id"], doc.equipment, doc.name
				),
				_("Scan the QR code of washer {0}.").format(doc.equipment),
			)
		return "equipment"
	if scanned["type"] == "wash_batch" and scanned["id"] == doc.name:
		return "wash_batch"
	raise _blocked(
		"SCAN_INVALID",
		_("Invalid code"),
		_("Code {0} is not the washer QR code or the code of batch {1}.").format(
			scanned["raw"] or "-", doc.name
		),
		_("Scan the QR code of washer {0}, then the QR code of batch {1}.").format(doc.equipment, doc.name),
	)


def _open_for_unload(batch, equipment_raw, batch_raw, station, for_update=False):
	"""Lô `Running` đã kiểm trạm và CẢ HAI mã quét (server không tin kiosk, Q15); trả ``(doc, máy)``."""
	doc = _batch_doc(batch, for_update=for_update)
	machine = frappe.db.get_value("Equipment", doc.equipment, list(EQUIPMENT_FIELDS), as_dict=True)
	_check_unload_station(station, machine)
	_require_running(doc)
	if _scan_kind(doc, equipment_raw) != "equipment" or _scan_kind(doc, batch_raw) != "wash_batch":
		raise _blocked(
			"SCAN_INVALID",
			_("Scan both codes"),
			_("Batch {0} needs the washer QR code and the batch QR code.").format(doc.name),
			_("Scan the QR code of washer {0}, then the QR code of batch {1}.").format(
				doc.equipment, doc.name
			),
		)
	return doc, machine


def scan_unload(batch, raw, station):
	"""Kiểm MỘT mã quét khi dỡ lô `batch` (Q15): ``{"ok": True, "kind": "equipment" | "wash_batch"}``.

	Máy khác máy của lô → EQUIPMENT_MISMATCH ngay; mã lô khác hoặc mã loại khác → SCAN_INVALID; lô đã đóng →
	BATCH_NOT_RUNNING; trạm không phải T2 hay cửa ra của máy → STATION_WRONG_STEP. Không ghi.
	"""
	doc = _batch_doc(batch)
	machine = frappe.db.get_value("Equipment", doc.equipment, list(EQUIPMENT_FIELDS), as_dict=True)
	_check_unload_station(station, machine)
	_require_running(doc)
	return {"ok": True, "kind": _scan_kind(doc, raw)}


def unload_context(batch, equipment_raw, batch_raw, station):
	"""Ngữ cảnh dỡ lô sau khi đã quét QR máy và QR lô: `lookup` + ``parameter_schema`` của chương trình."""
	doc, _machine = _open_for_unload(batch, equipment_raw, batch_raw, station)
	return {**_describe(doc), "parameter_schema": _parameters(doc.program)}


# --- Dữ liệu chu trình nhập tay có xác nhận (FR-M2-24.3/.5, BRU-REP-015) --------------------------------------


def _number(value):
	if value is None or (isinstance(value, str) and not value.strip()):
		return None
	if isinstance(value, bool):
		return None
	try:
		return float(str(value).strip().replace(",", "."))
	except ValueError:
		return None


def _outside(value, low, high):
	"""Ngoài dải theo `param_schema`: giới hạn bằng 0 là không đặt, dải một phía hợp lệ (Q8)."""
	low, high = flt(low), flt(high)
	return bool((low and value < low) or (high and value > high))


def _datetime_or_none(value):
	if not value:
		return None
	try:
		return get_datetime(value).replace(tzinfo=None)
	except Exception:
		return None


def save_manual_data(
	batch,
	equipment_raw,
	batch_raw,
	values,
	reported_result,
	started_at,
	ended_at,
	machine_alerts,
	machine_file,
	confirmed,
	client_ts,
	employee=None,
	station=None,
):
	"""Lưu dữ liệu chu trình nhập tay của lô `Running` (nguồn `Manual`); trả ``{"data_complete", "needs_review",
	"missing"}``.

	`values` là ``[{"parameter_name", "value"}]`` theo chương trình; giá trị ngoài dải không chặn mà đặt
	``needs_review`` (Q8). `reported_result` (kết quả máy báo) chỉ là thông tin (Q14). `started_at`/`ended_at` là giờ
	hệ thống. Dữ liệu đủ (Q6) khi: mọi tham số `required` có giá trị, có giờ kết thúc không trước giờ bắt đầu, có ảnh
	bản in nếu máy có bản in, và người nhập (`employee`, Employee của phiên) đã tick xác nhận. Lưu lại được nhiều lần
	trước khi kết luận.
	"""
	client_time.check_skew(client_ts)
	doc, machine = _open_for_unload(batch, equipment_raw, batch_raw, station, for_update=True)
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
	if cint(machine.has_printout) and not machine_file:
		missing.append(MISSING_PRINTOUT)
	if not confirmed:
		missing.append(MISSING_CONFIRMATION)
	doc.update(
		{
			"machine_data": frappe.as_json(
				{
					"parameters": parameters,
					"alerts": machine_alerts or None,
					"reported_result": reported_result if reported_result in RESULTS else None,
					"missing": missing,
				}
			),
			"machine_files": machine_file or None,
			"started_at": started,
			"ended_at": ended,
			"data_source": "Manual",
			"data_complete": 0 if missing else 1,
			"needs_review": 1 if review else 0,
			"manual_confirmed_by": employee if confirmed else None,
			"manual_confirmed_at": _system_time(client_ts) if confirmed else None,
		}
	)
	doc.flags.tc_washing = True
	doc.save(ignore_permissions=True)
	return {"data_complete": doc.data_complete, "needs_review": doc.needs_review, "missing": missing}


# --- Kết luận lô (FR-M2-04.3/.4/.5/.6, BRU-REP-002, BRU-REP-015) ---------------------------------------------


def _result_invalid(reason):
	return _blocked(
		"RESULT_INVALID",
		_("Result is not valid"),
		reason,
		_("Choose Pass or Fail for the cycle and the cleaning test."),
	)


def _reviewer(session, proof):
	"""User R02 đã xác nhận Đạt bằng PIN proof của phiên `session` (Q7); thiếu, sai hoặc không phải R02 → chặn."""
	reviewer = None
	if proof:
		try:
			reviewer = station_auth.consume_session_pin_proof(session, proof).user
		except BlockedError:
			reviewer = None
	if not reviewer or REVIEWER_ROLE not in frappe.get_roles(reviewer):
		raise _blocked(
			"R02_CONFIRM_REQUIRED",
			_("R02 confirmation required"),
			_("This washer has no connection and no printout, so a Pass needs the confirmation of R02."),
			_("Ask R02 to sign in at this station and enter the PIN, then record the result again."),
		)
	return reviewer


def set_result(
	batch,
	result,
	station,
	equipment_raw,
	batch_raw,
	clean_test,
	reviewer_proof=None,
	note=None,
	client_ts=None,
	session=None,
):
	"""Kết luận lô `Running`: ghi cổng T2 cùng một kết quả cho MỌI bộ và đóng lô (ghi sổ) trong một savepoint.

	Kiểm lại trạm và hai mã quét (Q15); chưa đủ dữ liệu chu trình → DATA_INCOMPLETE cho cả Đạt lẫn Không đạt (Q6,
	FR-M2-04.6). Đạt cần test làm sạch Đạt (Q14) và, với máy không kết nối và không bản in, PIN proof của R02 trên
	phiên `session` (Q7). Không đạt: mọi bộ về Xử lý lại, ``nc_pending = 1``, Audit Log ``WashFailed`` và hook
	`tracecore_after_wash_failed` (NC tự tạo là FEAT-030, Q22); Đạt gọi `tracecore_after_wash_complete`. Lỗi giữa
	chừng hoàn tác về savepoint: không bộ nào có cổng mới, lô vẫn `Running`.

	Trả ``{"batch", "result", "sets": [{"set_id", "status", "redo_count"}], "incident_id"}``; ``incident_id`` là NC tự
	tạo khi Không đạt (FEAT-030), None khi Đạt.
	"""
	client_ts = client_ts or client_time.utc_now()
	client_time.check_skew(client_ts)
	frappe.db.savepoint(RESULT_SAVEPOINT)
	try:
		return _set_result(
			batch,
			result,
			station,
			equipment_raw,
			batch_raw,
			clean_test,
			reviewer_proof,
			note,
			client_ts,
			session,
		)
	except Exception:
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=RESULT_SAVEPOINT)
		raise


def _set_result(
	batch, result, station, equipment_raw, batch_raw, clean_test, reviewer_proof, note, client_ts, session
):
	doc, machine = _open_for_unload(batch, equipment_raw, batch_raw, station, for_update=True)
	if result not in RESULTS or clean_test not in RESULTS:
		raise _result_invalid(_("The result and the cleaning test must each be Pass or Fail."))
	if not cint(doc.data_complete):
		data = frappe.parse_json(doc.machine_data) if doc.machine_data else {}
		raise _blocked(
			"DATA_INCOMPLETE",
			_("Cycle data is incomplete"),
			_("Wash batch {0} has no complete, confirmed cycle data, so it cannot be closed.").format(
				doc.name
			),
			_(
				"Enter the cycle data from the washer screen or printout and confirm it, then record the result."
			),
			items=(data or {}).get("missing") or [_("cycle data")],
		)
	reviewer = None
	if result == "Pass":
		if clean_test != "Pass":
			raise _result_invalid(_("A batch can pass only when the cleaning test has passed."))
		if not cint(machine.is_connected) and not cint(machine.has_printout):
			reviewer = _reviewer(session, reviewer_proof)
	sets = sorted(row.set_unit for row in doc.set_units)
	for set_id in sets:
		step_gate.record(set_id, STEP, result, ref_doctype="Wash Batch", ref_name=doc.name, station=station)
	at = _system_time(client_ts)
	doc.update(
		{
			"status": CLOSED_STATUS[result],
			"cycle_result": result,
			"clean_test_result": clean_test,
			"result_source": "Manual",
			"unload_scan_equipment": doc.equipment,
			"unload_scan_at": at,
			"result_note": note or None,
			"reviewer": reviewer,
			"reviewed_at": at if reviewer else None,
			"nc_pending": 1 if result == "Fail" else 0,
		}
	)
	doc.flags.tc_washing = True
	doc.flags.ignore_permissions = True  # quyền thao tác đã kiểm ở RPC theo role trạm (Q20)
	doc.submit()
	ctx = {
		"batch": doc.name,
		"equipment": doc.equipment,
		"program": doc.program,
		"sets": sets,
		"chemicals": [{"item": row.item, "lot": row.lot, "qty": flt(row.qty)} for row in doc.chemicals],
		"result": result,
	}
	if result == "Fail":
		audit.log(
			"Update",
			"Wash Batch",
			doc.name,
			new={"event": "WashFailed", "sets": sets},
			reason="WashFailed",
			station=station,
			client_ts=client_ts,
		)
		extension.run(AFTER_FAILED_HOOK, ctx)
	else:
		extension.run(AFTER_COMPLETE_HOOK, ctx)
	states = []
	for set_id in sets:
		status = frappe.db.get_value("Set Unit", set_id, "status")
		redo = next(g["redo_count"] for g in step_gate.gates(set_id) if g["step"] == STEP)
		states.append({"set_id": set_id, "status": status, "redo_count": redo})
	incident = (
		frappe.db.get_value(
			"Incident CAPA", {"source_doctype": "Wash Batch", "source_name": doc.name}, "name"
		)  # NC tự tạo qua hook tracecore_after_wash_failed (FEAT-030)
		if result == "Fail"
		else None
	)
	return {"batch": doc.name, "result": result, "sets": states, "incident_id": incident}
