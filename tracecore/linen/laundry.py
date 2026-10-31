"""Lô giặt theo kg: tạo, kiểm quy tắc, hoàn tất (FEAT-034, UC-17, FR-M3-03, .1-.4, FR-M3-04; BRU-LIN-001, BRU-LIN-003,
BRU-EQP-002; architecture §5.3 DT-LAUNDRY, A-50).

M3 không import M5/M6/M7: trừ hóa chất và chi phí/kg do hook `tracecore_after_laundry_complete` (`inventory.consume`,
`costing.from_laundry`). Từ chối nghiệp vụ là `BlockedError` (mã HTTP ở `core.errors`).
"""

import math

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from tracecore.core import extension
from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Laundry Batch"
WASHER_TYPE = "Laundry Washer"
DRYER_TYPE = "Dryer"
IN_HOUSE = "In-house"
OUTSOURCED = "Outsourced"
RUNNING = "Running"
PASSED = "Passed"
FAILED = "Failed"
MIN_CONTAMINATED_C = 71  # FR-M3-03.2: đồ nhiễm giặt dưới 71 °C phải có hóa chất khử khuẩn
WEIGHT_DIGITS = 3
AFTER_COMPLETE_HOOK = "tracecore_after_laundry_complete"
EQUIPMENT_LABELS = {WASHER_TYPE: "laundry washer", DRYER_TYPE: "dryer"}


def _blocked(code, title, reason, action, items=None, **fields):
	return BlockedError(Block(code, title, reason, action, items=items, **fields))


def _number(value):
	"""Số hữu hạn hoặc None (chuỗi, bool, NaN, vô cực không phải số)."""
	if isinstance(value, bool) or value is None or value == "":
		return None
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	return number if math.isfinite(number) else None


def _flag(value):
	return 1 if value in (1, True, "1", "true", "True") else 0


# --- Thiết bị --------------------------------------------------------------------------------------------


def check_equipment(equipment, equipment_type):
	"""Máy `equipment` phải là `equipment_type` và Sẵn sàng; không thì `BlockedError` (FR-M3-03.4, BRU-EQP-002)."""
	row = (
		frappe.db.get_value("Equipment", equipment, ["equipment_type", "status", "capacity_kg"], as_dict=True)
		if isinstance(equipment, str) and equipment
		else None
	)
	label = _(EQUIPMENT_LABELS[equipment_type])
	if not row or row.equipment_type != equipment_type:
		raise _blocked(
			"LAUNDRY_EQUIPMENT_INVALID",
			_("Machine is not valid"),
			_("Equipment {0} is not a {1}.").format(equipment or "-", label),
			_("Choose a {0} from the list.").format(label),
		)
	if row.status != "Ready":
		raise _blocked(
			"EQUIPMENT_NOT_READY",
			_("Machine is not ready"),
			_("Equipment {0} is {1}.").format(equipment, _(row.status, context="Equipment")),
			_("Use another machine, or call R02 to check the machine."),
		)
	return row


# --- Tham số của lô --------------------------------------------------------------------------------------


def _weight_and_flag(loads):
	"""``(kg, contaminated)`` từ ``loads = [{"kg", "contaminated"}]``; kg ≤ 0 → LAUNDRY_WEIGHT_INVALID, trộn cờ → LAUNDRY_MIXED."""
	if not isinstance(loads, list) or not loads:
		raise _blocked(
			"LAUNDRY_WEIGHT_INVALID",
			_("Weight is not valid"),
			_("The batch has no load with a weight."),
			_("Enter the weight in kg of the linen."),
		)
	total, flags = 0.0, set()
	for index, row in enumerate(loads, 1):
		kg = _number(row.get("kg")) if isinstance(row, dict) else None
		if kg is None or kg <= 0:
			raise _blocked(
				"LAUNDRY_WEIGHT_INVALID",
				_("Weight is not valid"),
				_("Load {0}: the weight must be a number greater than 0.").format(index),
				_("Enter the weight in kg of the linen."),
			)
		total += kg
		flags.add(_flag(row.get("contaminated", 1)))
	if len(flags) > 1:
		raise _blocked(
			"LAUNDRY_MIXED",
			_("Contaminated and clean linen are mixed"),
			_("A batch cannot hold both contaminated and clean linen."),
			_("Split the linen into two batches."),
		)
	return round(total, WEIGHT_DIGITS), flags.pop()


def _chemicals(rows):
	"""Danh sách ``[{"item", "qty"}]`` đã chuẩn hóa; Item không tồn tại hoặc qty âm → LAUNDRY_CHEMICAL_INVALID."""
	prepared = []
	for index, row in enumerate(rows or [], 1):
		item = row.get("item") if isinstance(row, dict) else None
		qty = _number(row.get("qty", 0)) if isinstance(row, dict) else None
		if not isinstance(item, str) or not frappe.db.exists("Item", item) or qty is None or qty < 0:
			raise _blocked(
				"LAUNDRY_CHEMICAL_INVALID",
				_("Chemical is not valid"),
				_("Row {0}: the item does not exist or the quantity is not valid.").format(index),
				_("Choose a chemical from the list and enter a quantity of 0 or more."),
			)
		prepared.append({"item": item, "qty": qty})
	return prepared


def _program(program, equipment):
	row = (
		frappe.db.get_value(
			"Process Program", program, ["equipment", "is_active", "temperature", "chemical"], as_dict=True
		)
		if isinstance(program, str) and program
		else None
	)
	if not row or not row.is_active or row.equipment != equipment:
		raise _blocked(
			"LAUNDRY_PROGRAM_INVALID",
			_("Program is not valid"),
			_("Program {0} is not an active program of machine {1}.").format(program or "-", equipment),
			_("Choose a program of this washer."),
		)
	return row


def _has_disinfectant(program, row, chemicals):
	items = {chemical["item"] for chemical in chemicals}
	items.update(
		frappe.get_all(
			"Program Consumable", filters={"parent": program, "parenttype": "Process Program"}, pluck="item"
		)
	)
	if row.chemical:
		items.add(row.chemical)
	return bool(items) and bool(
		frappe.db.exists("Item", {"name": ["in", list(items)], "tc_is_disinfectant": 1})
	)


# --- Tạo lô ----------------------------------------------------------------------------------------------


def _check_redo(redo_of):
	if not redo_of:
		return
	status = frappe.db.get_value(DOCTYPE, redo_of, "status") if isinstance(redo_of, str) else None
	if status != FAILED:
		raise _blocked(
			"LAUNDRY_REDO_INVALID",
			_("Batch cannot be redone"),
			_("Only a failed batch can be washed again; {0} is not.").format(redo_of),
			_("Choose a failed batch, or start a new batch."),
		)


def start(
	station,
	operator,
	loads,
	equipment=None,
	program=None,
	chemicals=None,
	batch_type=IN_HOUSE,
	vendor=None,
	price_per_kg=None,
	redo_of=None,
	note=None,
):
	"""Tạo lô giặt Đang chạy (UC-17 bước 1-3): kiểm kg, trộn nhiễm, máy, tải máy, chương trình, nhiệt độ (FR-M3-03.1-.4)."""
	weight, contaminated = _weight_and_flag(loads)
	chemicals = _chemicals(chemicals)
	_check_redo(redo_of)
	values = {
		"doctype": DOCTYPE,
		"batch_type": batch_type,
		"status": RUNNING,
		"weight_kg": weight,
		"contaminated": contaminated,
		"operator": operator,
		"station": station,
		"redo_of": redo_of,
		"started_at": now_datetime(),
		"result_note": note,
	}
	if batch_type == OUTSOURCED:
		price = _number(price_per_kg)
		if not vendor or price is None or price <= 0:
			raise _blocked(
				"LAUNDRY_VENDOR_REQUIRED",
				_("Vendor and price are required"),
				_("An outsourced batch needs the vendor and a price per kg greater than 0."),
				_("Enter the vendor and the price per kg."),
			)
		values.update(vendor=vendor, price_per_kg=price)
	else:
		washer = check_equipment(equipment, WASHER_TYPE)
		if washer.capacity_kg and weight > washer.capacity_kg:
			raise _blocked(
				"LAUNDRY_OVER_CAPACITY",
				_("Weight is over the machine capacity"),
				_("The load is {0} kg but machine {1} takes {2} kg.").format(
					weight, equipment, washer.capacity_kg
				),
				_("Reduce the load or use a larger washer."),
			)
		row = _program(program, equipment)
		if (
			contaminated
			and (row.temperature or 0) < MIN_CONTAMINATED_C
			and not _has_disinfectant(program, row, chemicals)
		):
			raise _blocked(
				"LAUNDRY_TEMP_TOO_LOW",
				_("Program is too cool for contaminated linen"),
				_("Program {0} washes at {1} C, below {2} C, and the batch has no disinfectant.").format(
					program, row.temperature or 0, MIN_CONTAMINATED_C
				),
				_("Choose a program of {0} C or more, or add a disinfectant chemical.").format(
					MIN_CONTAMINATED_C
				),
			)
		values.update(equipment=equipment, program=program)
	doc = frappe.get_doc(values)
	for chemical in chemicals:
		doc.append("chemicals", chemical)
	return doc.insert(ignore_permissions=True)


# --- Hoàn tất --------------------------------------------------------------------------------------------


def _positive_int(value):
	number = _number(value)
	return int(number) if number is not None and number > 0 and number == int(number) else None


def _required_check(value, name):
	if value is None or value == "":
		raise _blocked(
			"LAUNDRY_RESULT_REQUIRED",
			_("Result check is missing"),
			_("Record whether the linen is {0}.").format(name),
			_("Tick or untick both checks, then complete the batch."),
		)
	return _flag(value)


def complete(batch, dryer=None, dry_temp_c=None, dry_minutes=None, clean_ok=None, dry_ok=None, note=None):
	"""Hoàn tất lô: ghi bước sấy và kết quả, ghi sổ rồi chạy hook trừ hóa chất và chi phí (UC-17 bước 4-6, FR-M3-04)."""
	row = (
		frappe.db.get_value(DOCTYPE, batch, ["status", "docstatus"], as_dict=True, for_update=True)
		if isinstance(batch, str) and batch
		else None
	)
	if not row:
		raise _blocked(
			"LAUNDRY_NOT_FOUND",
			_("Laundry batch not found"),
			_("Laundry batch {0} does not exist.").format(batch or "-"),
			_("Open the list of running batches and choose one."),
		)
	if row.status != RUNNING or row.docstatus != 0:
		raise _blocked(
			"LAUNDRY_NOT_RUNNING",
			_("Batch is already finished"),
			_("Laundry batch {0} is {1}.").format(batch, _(row.status)),
			_("Choose a running batch."),
		)
	doc = frappe.get_doc(DOCTYPE, batch)
	clean, dry = _required_check(clean_ok, _("clean")), _required_check(dry_ok, _("dry"))
	if doc.batch_type == IN_HOUSE:
		check_equipment(dryer, DRYER_TYPE)
		temperature, minutes = _positive_int(dry_temp_c), _positive_int(dry_minutes)
		if temperature is None or minutes is None:
			raise _blocked(
				"LAUNDRY_DRY_INVALID",
				_("Drying data is not valid"),
				_("The drying temperature and time must be whole numbers greater than 0."),
				_("Enter the dryer temperature in C and the time in minutes."),
			)
		doc.update({"dryer": dryer, "dry_temp_c": temperature, "dry_minutes": minutes})
	doc.update(
		{
			"clean_ok": clean,
			"dry_ok": dry,
			"status": PASSED if clean and dry else FAILED,
			"ended_at": now_datetime(),
		}
	)
	if note:
		doc.result_note = note
	if doc.batch_type == OUTSOURCED:
		doc.cost_total = flt(doc.weight_kg * doc.price_per_kg)
		doc.cost_per_kg = flt(doc.price_per_kg)
	doc.submit()
	extension.run(AFTER_COMPLETE_HOOK, _context(doc))
	doc.reload()
	return doc


def _context(doc):
	"""Ngữ cảnh của hook sau hoàn tất (xem A-50 (c))."""
	return {
		"batch": doc.name,
		"batch_type": doc.batch_type,
		"equipment": doc.equipment or None,
		"program": doc.program or None,
		"kg": doc.weight_kg,
		"chemicals": [{"item": row.item, "qty": row.qty} for row in doc.chemicals],
		"result": "Pass" if doc.status == PASSED else "Fail",
	}


# --- Dữ liệu cho màn trạm --------------------------------------------------------------------------------


def view(doc):
	"""Lô giặt cho màn trạm: trạng thái, kg, thiết bị, chi phí và chi phí/kg."""
	fields = (
		"name status batch_type weight_kg contaminated equipment program dryer started_at ended_at "
		"cost_electricity cost_water cost_chemical cost_labor cost_total cost_per_kg cost_note redo_of vendor price_per_kg"
	).split()
	return {field: doc.get(field) for field in fields}


def context():
	"""Máy giặt/sấy Sẵn sàng, chương trình giặt và hóa chất để màn trạm chọn, cùng các lô đang chạy."""
	machines = frappe.get_all(
		"Equipment",
		filters={"equipment_type": ["in", [WASHER_TYPE, DRYER_TYPE]], "status": "Ready"},
		fields=["name", "equipment_name", "equipment_type", "capacity_kg"],
		order_by="equipment_name asc",
	)
	washers = [row.name for row in machines if row.equipment_type == WASHER_TYPE]
	programs = frappe.get_all(
		"Process Program",
		filters={"equipment": ["in", washers or [""]], "is_active": 1},
		fields=["name", "program_name", "equipment", "temperature", "duration_min"],
		order_by="program_code asc",
	)
	norms = frappe.get_all(
		"Program Consumable",
		filters={"parenttype": "Process Program", "parent": ["in", [row.name for row in programs] or [""]]},
		fields=["parent", "item", "qty_per_kg", "qty_per_load"],
		order_by="idx asc",
	)
	for program in programs:
		program["norms"] = [row for row in norms if row.parent == program.name]
	return {
		"washers": [row for row in machines if row.equipment_type == WASHER_TYPE],
		"dryers": [row for row in machines if row.equipment_type == DRYER_TYPE],
		"programs": programs,
		"chemicals": frappe.get_all(
			"Item",
			filters={"tc_item_group_cssd": "Chemical", "disabled": 0},
			fields=["name", "item_name", "tc_is_disinfectant"],
			order_by="item_name asc",
		),
		"running": frappe.get_all(
			DOCTYPE,
			filters={"status": RUNNING, "docstatus": 0},
			fields=["name", "weight_kg", "contaminated", "equipment", "program", "batch_type", "started_at"],
			order_by="started_at asc",
		),
	}
