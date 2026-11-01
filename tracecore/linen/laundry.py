"""Lô giặt theo kg: tạo, kiểm quy tắc, hoàn tất (FEAT-034, UC-17, FR-M3-03, .1-.4, FR-M3-04; BRU-LIN-001, BRU-LIN-003,
BRU-EQP-002; architecture §5.3 DT-LAUNDRY, A-50).

M3 không import M5/M6/M7: trừ hóa chất và chi phí/kg do hook `tracecore_after_laundry_complete` (`inventory.consume`,
`costing.from_laundry`). Từ chối nghiệp vụ là `BlockedError` (mã HTTP ở `core.errors`).
"""

import math

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from tracecore.core import extension, program_norm
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
DEFAULT_DEVIATION_PERCENT = 10  # FR-M3-09.1: dùng khi TraceCore Settings chưa khai
DEVIATION_DIGITS = 2
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


def _program(program, equipment, action=None):
	row = (
		frappe.db.get_value(
			"Process Program",
			program,
			["equipment", "is_active", "temperature", "duration_min", "chemical", "max_load_kg"],
			as_dict=True,
		)
		if isinstance(program, str) and program
		else None
	)
	if not row or not row.is_active or row.equipment != equipment:
		raise _blocked(
			"LAUNDRY_PROGRAM_INVALID",
			_("Program is not valid"),
			_("Program {0} is not an active program of machine {1}.").format(program or "-", equipment),
			action or _("Choose a program of this washer."),
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


def _check_in_house(equipment, program, weight, contaminated, chemicals):
	"""Quy tắc của lô tự giặt, dùng chung cho trạm và form Desk (FR-M3-03.2-.4, FR-M3-09.2)."""
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
	if row.max_load_kg and weight > row.max_load_kg:
		raise _blocked(
			"LAUNDRY_OVER_PROGRAM_LOAD",
			_("Weight is over the program load"),
			_("The load is {0} kg but program {1} takes {2} kg.").format(weight, program, row.max_load_kg),
			_("Reduce the load or choose another program."),
		)
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


def _check_dry(dryer, dry_program):
	"""Máy sấy phải Sẵn sàng; chương trình sấy phải của đúng máy sấy và cần có máy sấy (A-104 D6). Trả dòng chương trình."""
	if dryer or dry_program:
		check_equipment(dryer, DRYER_TYPE)
	if dry_program:
		return _program(dry_program, dryer, _("Choose a program of this dryer."))
	return None


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
	dryer=None,
	dry_program=None,
):
	"""Tạo lô giặt Đang chạy (UC-17 bước 1-3): kiểm kg, trộn nhiễm, máy, tải máy, chương trình, nhiệt độ (FR-M3-03.1-.4).

	Máy sấy và chương trình sấy chọn được ngay hoặc khi hoàn tất; định mức do `validate_batch` điền vào lô (A-104).
	"""
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
		_check_in_house(equipment, program, weight, contaminated, chemicals)
		_check_dry(dryer, dry_program)
		values.update(equipment=equipment, program=program, dryer=dryer, dry_program=dry_program)
	doc = frappe.get_doc(values)
	doc.flags.tc_service = True
	for chemical in chemicals:
		doc.append("chemicals", chemical)
	return doc.insert(ignore_permissions=True)


# --- Định mức và thực tế (A-104) --------------------------------------------------------------------------


def deviation_threshold():
	"""Ngưỡng % lệch định mức phải có lý do (FR-M3-09.1)."""
	value = frappe.db.get_single_value("TraceCore Settings", "laundry_norm_deviation_percent")
	return flt(value) or DEFAULT_DEVIATION_PERCENT


def _follow(actual, old_norm, new_norm):
	"""Số thực tế đi theo định mức cho đến khi người dùng sửa (A-104 D4)."""
	return new_norm if flt(actual) in (0, flt(old_norm)) else flt(actual)


def _fill_chemicals(doc, lines):
	"""Dòng hóa chất theo định mức: dòng đã có giữ số người dùng sửa, dòng 0 → định mức (như trừ kho, A-50), dòng định mức
	bị xóa được thêm lại để chi phí, trừ kho và báo cáo cùng một số."""
	wanted = {(line["item"], line["program"]): line for line in lines}
	for row in list(doc.chemicals):
		key = (row.item, row.program) if row.program else next((k for k in wanted if k[0] == row.item), None)
		line = wanted.pop(key, None) if key else None
		if not line:
			if row.program and flt(row.qty) == flt(row.norm_qty):
				doc.remove(row)  # dòng tự điền của chương trình đã đổi, chưa ai sửa
				continue
			row.update({"program": None, "norm_qty": 0})
		else:
			if flt(row.qty) in (0, flt(row.norm_qty)):
				row.qty = line["qty"]
			row.update({"program": line["program"], "norm_qty": line["qty"]})
		row.uom = frappe.db.get_value("Item", row.item, "stock_uom")
	for line in wanted.values():
		doc.append(
			"chemicals",
			{
				"item": line["item"],
				"program": line["program"],
				"uom": line["uom"],
				"qty": line["qty"],
				"norm_qty": line["qty"],
			},
		)


def _deviation(doc):
	"""% lệch lớn nhất trên điện, nước, từng dòng hóa chất có định mức > 0 (A-104 D5)."""
	pairs = [
		(doc.actual_kwh, doc.norm_kwh),
		(doc.actual_dry_kwh, doc.norm_dry_kwh),
		(doc.actual_water_l, doc.norm_water_l),
		*((row.qty, row.norm_qty) for row in doc.chemicals),
	]
	gaps = [abs(flt(actual) - flt(norm)) / flt(norm) * 100 for actual, norm in pairs if flt(norm) > 0]
	return round(max(gaps, default=0), DEVIATION_DIGITS)


def fill_norm(doc):
	"""Ghi định mức của chương trình giặt, sấy vào lô và tính mức lệch; lô thuê ngoài không có định mức."""
	if doc.batch_type != IN_HOUSE or not doc.program:
		return
	kg = flt(doc.weight_kg)
	wash = program_norm.of(doc.program, kg)
	dry = program_norm.of(doc.dry_program, kg) if doc.dry_program else None
	dry_kwh = dry["kwh"] if dry else 0
	doc.update(
		{
			"actual_kwh": _follow(doc.actual_kwh, doc.norm_kwh, wash["kwh"]),
			"norm_kwh": wash["kwh"],
			"actual_water_l": _follow(doc.actual_water_l, doc.norm_water_l, wash["water_l"]),
			"norm_water_l": wash["water_l"],
			"actual_dry_kwh": _follow(doc.actual_dry_kwh, doc.norm_dry_kwh, dry_kwh),
			"norm_dry_kwh": dry_kwh,
		}
	)
	_fill_chemicals(doc, wash["lines"] + (dry["lines"] if dry else []))
	doc.norm_deviation_pct = _deviation(doc)


def _changed(doc, fields):
	return doc.is_new() or any(doc.has_value_changed(field) for field in fields)


def _desk_error(doc, error):
	"""Trạm nhận `BlockedError` để trả mã lỗi; form Desk cần thông báo hiện trên màn."""
	if doc.flags.tc_service:
		raise error
	block = error.block
	frappe.throw(" ".join((block.reason, block.action)), title=block.title)


def before_insert_batch(doc):
	doc.status = doc.status or RUNNING
	doc.started_at = doc.started_at or now_datetime()


def validate_batch(doc):
	"""Controller Laundry Batch: quy tắc khi lô đổi máy, chương trình, kg (form Desk; trạm đã kiểm), rồi điền định mức.

	Máy khóa giữa chừng không chặn lưu hay hoàn tất lô đang chạy: chỉ kiểm khi giá trị đổi.
	"""
	if doc.batch_type != IN_HOUSE:
		return
	try:
		if not doc.flags.tc_service:
			if _changed(doc, ("equipment", "program", "weight_kg", "contaminated")):
				rows = [{"item": row.item, "qty": row.qty} for row in doc.chemicals]
				_check_in_house(doc.equipment, doc.program, flt(doc.weight_kg), doc.contaminated, rows)
			if _changed(doc, ("dryer", "dry_program")):
				_check_dry(doc.dryer, doc.dry_program)
	except BlockedError as error:
		_desk_error(doc, error)
	fill_norm(doc)


def before_submit_batch(doc):
	"""Lô chỉ ghi sổ qua Hoàn tất (hook trừ kho, chi phí luôn chạy; A-104 D8); lệch quá ngưỡng phải có lý do (BRU-LIN-006)."""
	try:
		if doc.status == RUNNING:
			raise _blocked(
				"LAUNDRY_USE_COMPLETE",
				_("Batch is still running"),
				_("Laundry batch {0} is still running.").format(doc.name),
				_("Use Complete batch so that stock and cost are recorded."),
			)
		threshold = deviation_threshold()
		if (
			doc.batch_type == IN_HOUSE
			and flt(doc.norm_deviation_pct) > threshold
			and not (doc.deviation_reason or "").strip()
		):
			raise _blocked(
				"LAUNDRY_DEVIATION_REASON_REQUIRED",
				_("Reason for the deviation is required"),
				_("Actual use differs from the norm by {0}%, above the {1}% threshold.").format(
					doc.norm_deviation_pct, threshold
				),
				_("Enter why the batch used a different amount."),
			)
	except BlockedError as error:
		_desk_error(doc, error)


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


def _actual(value):
	"""Số thực tế người dùng nhập: bỏ trống → None (giữ số trên lô); âm hoặc không phải số → LAUNDRY_ACTUAL_INVALID."""
	if value is None or value == "":
		return None
	number = _number(value)
	if number is None or number < 0:
		raise _blocked(
			"LAUNDRY_ACTUAL_INVALID",
			_("Actual use is not valid"),
			_("Actual water and power must be numbers of 0 or more."),
			_("Enter the actual water in litres and the actual power in kWh."),
		)
	return number


def complete(
	batch,
	dryer=None,
	dry_temp_c=None,
	dry_minutes=None,
	clean_ok=None,
	dry_ok=None,
	note=None,
	dry_program=None,
	actual_kwh=None,
	actual_dry_kwh=None,
	actual_water_l=None,
	deviation_reason=None,
):
	"""Hoàn tất lô: ghi bước sấy, số thực tế và kết quả, ghi sổ rồi chạy hook trừ hóa chất và chi phí (UC-17 bước 4-6, FR-M3-04,
	FR-M3-09). Tham số bỏ trống giữ giá trị đã có trên lô; nhiệt độ và thời gian sấy mặc định theo chương trình sấy."""
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
		dryer = dryer or doc.dryer
		dry_program = dry_program or doc.dry_program
		check_equipment(dryer, DRYER_TYPE)
		dry_row = _check_dry(dryer, dry_program)
		if dry_row:
			dry_temp_c = dry_temp_c or dry_row.temperature
			dry_minutes = dry_minutes or dry_row.duration_min
		temperature, minutes = _positive_int(dry_temp_c), _positive_int(dry_minutes)
		if temperature is None or minutes is None:
			raise _blocked(
				"LAUNDRY_DRY_INVALID",
				_("Drying data is not valid"),
				_("The drying temperature and time must be whole numbers greater than 0."),
				_("Enter the dryer temperature in C and the time in minutes."),
			)
		doc.update(
			{"dryer": dryer, "dry_program": dry_program, "dry_temp_c": temperature, "dry_minutes": minutes}
		)
		for field, value in (
			("actual_kwh", actual_kwh),
			("actual_dry_kwh", actual_dry_kwh),
			("actual_water_l", actual_water_l),
		):
			number = _actual(value)
			if number is not None:
				doc.set(field, number)
		if deviation_reason:
			doc.deviation_reason = deviation_reason
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
	doc.flags.tc_service = True
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
		"cost_electricity cost_water cost_chemical cost_labor cost_total cost_per_kg cost_note redo_of vendor price_per_kg "
		"dry_program norm_kwh actual_kwh norm_dry_kwh actual_dry_kwh norm_water_l actual_water_l norm_deviation_pct "
		"deviation_reason norm_cost_electricity norm_cost_water norm_cost_chemical norm_cost_total norm_cost_per_kg"
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
	dryers = [row.name for row in machines if row.equipment_type == DRYER_TYPE]
	programs = frappe.get_all(
		"Process Program",
		filters={"equipment": ["in", washers or [""]], "is_active": 1},
		fields=["name", "program_name", "equipment", "temperature", "duration_min", "max_load_kg"],
		order_by="program_code asc",
	)
	dry_programs = frappe.get_all(
		"Process Program",
		filters={"equipment": ["in", dryers or [""]], "is_active": 1},
		fields=["name", "program_name", "equipment", "temperature", "duration_min", "kwh_per_cycle"],
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
		"dry_programs": dry_programs,
		"deviation_percent": deviation_threshold(),
		"chemicals": frappe.get_all(
			"Item",
			filters={"tc_item_group_cssd": "Chemical", "disabled": 0},
			fields=["name", "item_name", "tc_is_disinfectant"],
			order_by="item_name asc",
		),
		"running": frappe.get_all(
			DOCTYPE,
			filters={"status": RUNNING, "docstatus": 0},
			fields=[
				"name",
				"weight_kg",
				"contaminated",
				"equipment",
				"program",
				"batch_type",
				"started_at",
				"dryer",
				"dry_program",
				"norm_kwh",
				"actual_kwh",
				"norm_water_l",
				"actual_water_l",
			],
			order_by="started_at asc",
		),
	}
