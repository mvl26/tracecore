"""Test hằng ngày và khóa máy (M5, FEAT-040; FR-M5-05 .1-.3, FR-M5-06 .1-.2; UC-23; BRU-EQP-001, BRU-EQP-002).

`record` ghi một Daily Test: test bắt buộc Đạt mở máy cho ngày, Không đạt khóa máy và đánh dấu NC chờ tạo (FEAT-030); test
của máy ngoài diện là tự nguyện, không khóa. Diện bắt buộc cấu hình theo từng viện trong TraceCore Settings (A-70).
`equipment_block` là hàm của hook ``tracecore_load_equipment_checks`` (T5) và
``tracecore_wash_equipment_checks`` (T2): chặn tạo mẻ/lô khi quá hạn kiểm định hoặc thiếu test ngày, M2 không import M5.
Test chạy máy đi theo `start_run` → `end_run` → `record` (A-84): trong lúc chạy máy không nạp được, kết quả chỉ ghi sau khi kết thúc.
`unlock_temp` là mở khóa tạm của R02 (quyền kiểm ở RPC): lý do, 1-24 giờ, không với thiết bị áp lực quá hạn kiểm định.
Trạng thái máy chỉ đổi bằng cờ ``flags.tc_equipment`` (xem `equipment.py`).
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime, today

from tracecore.core import audit, error_codes, zones
from tracecore.core.errors import Block, BlockedError
from tracecore.equipment import chemical_lots

SETTINGS = "TraceCore Settings"
MODE_NONE = "Not Required"
MODE_ALL = "All Sterilizers"
MODE_SELECTED = "Selected Sterilizers"
MODES = (MODE_NONE, MODE_ALL, MODE_SELECTED)
STEAM = "Steam Sterilizer"
PLASMA = "Plasma Sterilizer"
STERILIZERS = (STEAM, PLASMA)  # chỉ máy tiệt khuẩn có thể thuộc diện bắt buộc (A-70)
WASHERS = ("Washer-Disinfector", "Ultrasonic Cleaner")
WASH_FUNCTIONS = ("WASH_LOAD", "WASH_UNLOAD")
STERILIZER_FUNCTIONS = ("STERI_LOAD", "STERI_UNLOAD")
LEAK = "leak"
# test ghi được theo loại máy; test nào bắt buộc do `required_tests` quyết định theo cấu hình
TESTS = {
	STEAM: ("bowie_dick", LEAK),
	PLASMA: ("plasma_daily",),
	"Washer-Disinfector": ("washer_cleaning",),
	"Ultrasonic Cleaner": ("washer_cleaning",),
}
# test phải chạy máy nên có lần chạy (A-84); washer_cleaning tự nguyện ghi thẳng
RUN_TESTS = ("bowie_dick", LEAK, "plasma_daily")
RUN_RUNNING, RUN_ENDED, RUN_RECORDED = "Running", "Ended", "Recorded"
RESULTS = ("Pass", "Fail")
PRESSURE_TYPES = (
	"Steam Sterilizer",
)  # thiết bị áp lực: quá hạn kiểm định thì không mở khóa tạm (FR-M5-06.2)
MAX_UNLOCK_HOURS = 24
MAX_REASON = 500
LOCK_DAILY_TEST = "Daily Test"
PHOTO_MISSING = "photo_missing"


def _blocked(code, title, reason, action, items=None, **fields):
	return BlockedError(Block(code, title, reason, action, items=items, **fields))


def _setting(field):
	# không qua cache: đổi Cài đặt có hiệu lực ngay (A-70)
	return frappe.db.get_single_value(SETTINGS, field, cache=False)


def mode():
	return _setting("daily_test_mode") or MODE_ALL


def ensure_settings():
	"""Ghi giá trị mặc định còn thiếu của mục Test hàng ngày (A-70); không đổi lựa chọn đã có của viện. Idempotent."""
	current = frappe.db.get_singles_dict(SETTINGS)
	defaults = {"daily_test_mode": MODE_ALL, "daily_test_steam_leak": 1, "daily_test_plasma": 1}
	for field, value in defaults.items():
		if current.get(field) in (None, ""):
			frappe.db.set_single_value(SETTINGS, field, value)


def required_tests(equipment_type, selected=0):
	"""Test bắt buộc của máy theo cấu hình; `selected` là ô tick trên phiếu máy, chỉ có tác dụng ở chế độ chọn máy."""
	current = mode()
	if (
		equipment_type not in STERILIZERS
		or current == MODE_NONE
		or (current == MODE_SELECTED and not cint(selected))
	):
		return []
	if equipment_type == PLASMA and not cint(_setting("daily_test_plasma")):
		return []
	tests = list(TESTS[equipment_type])
	if LEAK in tests and not cint(_setting("daily_test_steam_leak")):
		tests.remove(LEAK)
	return tests


def _equipment(name, for_update=False):
	if not name or not frappe.db.exists("Equipment", name):
		raise _blocked(
			"EQUIPMENT_NOT_FOUND",
			_("Equipment not found"),
			_("Equipment {0} does not exist.").format(name or "-"),
			_("Scan the QR code on the machine."),
		)
	return frappe.get_doc("Equipment", name, for_update=for_update)


def _invalid(reason):
	return _blocked(
		"TEST_INVALID",
		_("Test is not valid"),
		reason,
		_("Check the test type, the result and the test lot, then record the test again."),
	)


def passed_today(equipment, test_type):
	"""Lần ghi mới nhất của ngày hôm nay của loại test này là Đạt."""
	result = frappe.db.get_value(
		"Daily Test",
		{"equipment": equipment, "test_type": test_type, "test_date": today()},
		"result",
		order_by="creation desc, name desc",
	)
	return result == "Pass"


# chỉ thị của mẻ (T5b) lấy được từ test hằng ngày cùng tên (A-23): Bowie-Dick chạy mỗi sáng trên máy hấp
DAILY_INDICATORS = ("bowie_dick",)


def load_indicator(equipment, indicator, on=None):
	"""Hook ``tracecore_load_daily_indicator`` (A-23): lần ghi mới nhất trong ngày `on` của test hằng ngày ứng với chỉ thị.

	Trả ``{"daily_test", "result", "test_date", "tested_at", "tested_by"}`` hoặc None (chỉ thị không lấy từ test hằng
	ngày, hoặc máy chưa có test đó trong ngày).
	"""
	if indicator not in DAILY_INDICATORS or not equipment:
		return None
	row = frappe.db.get_value(
		"Daily Test",
		{
			"equipment": equipment,
			"test_type": indicator,
			"test_date": getdate(on or today()),
			"result": ["is", "set"],  # lần chạy chưa đọc kết quả không che kết quả đã có (A-84)
		},
		["name", "result", "test_date", "tested_at", "tested_by"],
		as_dict=True,
		order_by="creation desc, name desc",
	)
	if not row:
		return None
	return {
		"daily_test": row.name,
		"result": row.result,
		"test_date": str(row.test_date),
		"tested_at": str(row.tested_at) if row.tested_at else None,
		"tested_by": row.tested_by,
	}


def optional_indicators(equipment):
	"""Hook ``tracecore_load_optional_indicators`` (A-70): chỉ thị lấy từ test ngày mà máy không bắt buộc theo cấu hình."""
	row = frappe.db.get_value("Equipment", equipment, ["equipment_type", "daily_test_required"], as_dict=True)
	if not row:
		return []
	required = required_tests(row.equipment_type, row.daily_test_required)
	return [kind for kind in DAILY_INDICATORS if kind not in required]


def missing_tests(equipment, equipment_type, selected=0):
	return [test for test in required_tests(equipment_type, selected) if not passed_today(equipment, test)]


def _apply(equipment, status=None, **fields):
	"""Lưu trạng thái/trường khóa của máy (cờ ``tc_equipment``); máy Ngừng sử dụng hoặc Sửa chữa giữ nguyên trạng thái."""
	doc = frappe.get_doc("Equipment", equipment, for_update=True)
	if status and doc.status not in ("Retired", "Repair"):
		doc.status = status
	doc.update(fields)
	doc.flags.tc_equipment = True
	doc.save(ignore_permissions=True)
	return doc


def open_run(equipment):
	"""Lần chạy test đang chạy của máy: ``{"name", "test_type", "started_at"}`` hoặc None."""
	return frappe.db.get_value(
		"Daily Test",
		{"equipment": equipment, "run_status": RUN_RUNNING},
		["name", "test_type", "started_at"],
		as_dict=True,
		order_by="creation desc, name desc",
	)


def unloaded_load(equipment):
	"""Mẻ chưa dỡ hoặc lô đang chạy trên máy: ``{"name", "status"}`` hoặc None. Đọc theo tên DocType, M5 không import M2."""
	load = frappe.db.get_value(
		"Sterilization Load",
		{
			"equipment": equipment,
			"status": ["in", ("Running", "Cycle Complete")],
			"docstatus": 0,
			"unload_scan_at": ["is", "not set"],
		},
		["name", "status"],
		as_dict=True,
		order_by="creation asc, name asc",
	)
	if load:
		return load
	return frappe.db.get_value(
		"Wash Batch", {"equipment": equipment, "status": "Running"}, ["name", "status"], as_dict=True
	)


def _latest_run(equipment, test_type):
	return frappe.db.get_value(
		"Daily Test",
		{"equipment": equipment, "test_type": test_type},
		["name", "run_status", "result"],
		as_dict=True,
		order_by="creation desc, name desc",
	)


def _check_run_test(machine, test_type):
	if test_type not in TESTS.get(machine.equipment_type, ()) or test_type not in RUN_TESTS:
		raise _invalid(
			_("Test {0} does not apply to {1}.").format(
				test_type, _(machine.equipment_type, context="Equipment")
			)
		)


def start_run(equipment, test_type, station, employee=None):
	"""Bắt đầu một lần chạy test (A-84): máy Đang test, không nạp được; trả ``{"daily_test", "started_at"}``.

	Máy còn mẻ chưa dỡ → EQUIPMENT_BUSY; máy đang chạy test khác → DAILY_TEST_RUN_OPEN.
	"""
	machine = _equipment(equipment, for_update=True)
	_check_run_test(machine, test_type)
	busy = unloaded_load(machine.name)
	if busy:
		raise _blocked(
			"EQUIPMENT_BUSY",
			_("Machine is still running a load"),
			_("Load {0} on machine {1} has not been unloaded.").format(busy.name, machine.name),
			_("Unload the load first, then start the test."),
			object_type="Equipment",
			object_name=machine.name,
		)
	running = open_run(machine.name)
	if running:
		raise _blocked(
			"DAILY_TEST_RUN_OPEN",
			_("A test is already running"),
			_("Machine {0} is running test {1}.").format(machine.name, running.test_type),
			_("End that test first."),
			object_type="Equipment",
			object_name=machine.name,
		)
	now = now_datetime()
	row = frappe.get_doc(
		{
			"doctype": "Daily Test",
			"equipment": machine.name,
			"test_type": test_type,
			"test_date": today(),
			"run_status": RUN_RUNNING,
			"started_at": now,
			"station": station,
			"tested_by_user": frappe.session.user,
			"tested_by": employee,
		}
	)
	row.flags.tc_daily_test = True
	row.insert(ignore_permissions=True)
	return {"daily_test": row.name, "started_at": now}


def end_run(equipment, test_type):
	"""Kết thúc lần chạy test đang chạy; trả ``{"daily_test", "ended_at"}``. Không có lần chạy → DAILY_TEST_RUN_NOT_ENDED."""
	machine = _equipment(equipment, for_update=True)
	_check_run_test(machine, test_type)
	latest = _latest_run(machine.name, test_type)
	if not latest or latest.run_status != RUN_RUNNING:
		raise _run_not_ended(machine.name, test_type, _("Test {0} of machine {1} is not running."))
	row = frappe.get_doc("Daily Test", latest.name)
	now = now_datetime()
	row.update({"run_status": RUN_ENDED, "ended_at": now})
	row.flags.tc_daily_test = True
	row.save(ignore_permissions=True)
	return {"daily_test": row.name, "ended_at": now}


def _run_not_ended(equipment, test_type, reason):
	return _blocked(
		"DAILY_TEST_RUN_NOT_ENDED",
		_("Test result cannot be recorded yet"),
		reason.format(test_type, equipment),
		_("Start the test, let it finish, end it, then read and record the result."),
		object_type="Equipment",
		object_name=equipment,
	)


def _ended_run(equipment, test_type):
	"""Dòng lần chạy mới nhất đã kết thúc và chưa có kết quả của loại test, hoặc DAILY_TEST_RUN_NOT_ENDED."""
	latest = _latest_run(equipment, test_type)
	if latest and latest.run_status == RUN_RUNNING:
		raise _run_not_ended(equipment, test_type, _("Test {0} of machine {1} is still running."))
	if not latest or latest.run_status != RUN_ENDED or latest.result:
		raise _run_not_ended(equipment, test_type, _("Test {0} of machine {1} has not been started."))
	return latest.name


def record(
	equipment,
	test_type,
	result,
	station,
	lot=None,
	lot_expiry=None,
	photo=None,
	employee=None,
	note=None,
	client_ts=None,
):
	"""Ghi một test hằng ngày (FR-M5-05); trả ``{"daily_test", "result", "locked", "unlocked", "warnings"}``.

	Test chạy máy phải có lần chạy đã kết thúc (A-84), kết quả ghi vào đúng dòng đó và `tested_by`, `tested_at` là người
	đọc, giờ đọc. Loại test phải thuộc bộ test của loại máy, kết quả Đạt/Không đạt, lô test bắt buộc và còn hạn (E2). Thiếu ảnh
	Bowie-Dick bắt buộc chỉ cảnh báo ``photo_missing`` (UC-23 E3). Test bắt buộc Không đạt khóa máy
	(``lock_reason = Daily Test``) và đặt ``nc_pending``; Đạt đủ bộ test của ngày thì mở lại máy đang bị khóa vì test.
	Test tự nguyện của máy ngoài diện chỉ được lưu lại (A-70).
	"""
	machine = _equipment(equipment, for_update=True)
	if test_type not in TESTS.get(machine.equipment_type, ()):
		raise _invalid(
			_("Test {0} does not apply to {1}.").format(
				test_type, _(machine.equipment_type, context="Equipment")
			)
		)
	if result not in RESULTS:
		raise _invalid(_("The result must be Pass or Fail."))
	run = _ended_run(machine.name, test_type) if test_type in RUN_TESTS else None
	lot = lot.strip() if isinstance(lot, str) else ""
	if not lot or not lot_expiry:
		raise _invalid(_("Enter the lot of the test pack and its expiry date."))
	if getdate(lot_expiry) < getdate(today()):
		raise _blocked(
			"TEST_LOT_EXPIRED",
			_("Test pack lot has expired"),
			_("The test pack lot {0} expired on {1}.").format(lot, frappe.utils.formatdate(lot_expiry)),
			_("Use a test pack from a lot that has not expired."),
		)
	now = now_datetime()
	mandatory = test_type in required_tests(machine.equipment_type, machine.daily_test_required)
	failed = result == "Fail" and mandatory
	values = {
		"result": result,
		"test_date": today(),
		"run_status": RUN_RECORDED,
		"lot": lot,
		"lot_expiry": lot_expiry,
		"photo": photo or None,
		"station": station,
		"tested_by_user": frappe.session.user,
		"tested_by": employee,
		"tested_at": now,
		"note": (note or "").strip()[:MAX_REASON] or None,
		"nc_pending": 1 if failed else 0,
	}
	if run:
		row = frappe.get_doc("Daily Test", run)
		row.update(values)
	else:
		row = frappe.get_doc(
			{"doctype": "Daily Test", "equipment": machine.name, "test_type": test_type, **values}
		)
	row.flags.tc_daily_test = True
	row.save(ignore_permissions=True)
	locked = unlocked = False
	if failed:
		if machine.status == "Ready":
			_apply(machine.name, status="Locked", lock_reason=LOCK_DAILY_TEST)
		locked = True
	elif (
		machine.status == "Locked"
		and machine.lock_reason == LOCK_DAILY_TEST
		and not missing_tests(machine.name, machine.equipment_type, machine.daily_test_required)
	):
		_apply(machine.name, status="Ready", lock_reason=None)
		unlocked = True
	return {
		"daily_test": row.name,
		"result": result,
		"locked": locked,
		"unlocked": unlocked,
		"warnings": [PHOTO_MISSING] if mandatory and test_type == "bowie_dick" and not photo else [],
	}


def _inspection_expired(row):
	return bool(row.inspection_due and getdate(row.inspection_due) < getdate(today()))


def _calibration_expired(row):
	return bool(row.calibration_due and getdate(row.calibration_due) < getdate(today()))


def _machine_row(equipment):
	return frappe.db.get_value(
		"Equipment",
		equipment,
		[
			"equipment_type",
			"status",
			"inspection_due",
			"calibration_due",
			"unlock_until",
			"daily_test_required",
		],
		as_dict=True,
	)


def equipment_block(equipment):
	"""Hàm của hook ``tracecore_load_equipment_checks`` / ``tracecore_wash_equipment_checks``: Block hoặc None (FR-M5-06).

	Quá hạn kiểm định → ``EQUIPMENT_INSPECTION_EXPIRED``; quá hạn hiệu chuẩn → ``EQUIPMENT_CALIBRATION_EXPIRED`` (A-43 M5);
	thiếu test bắt buộc theo cấu hình → ``DAILY_TEST_REQUIRED`` kèm danh sách. Máy đang được R02 mở khóa tạm (``unlock_until`` chưa hết) bỏ
	qua test ngày và hiệu chuẩn quá hạn, và bỏ qua kiểm định quá hạn nếu không phải thiết bị áp lực. Máy
	``Locked``/``Repair`` đã bị chặn trước đó bởi ``EQUIPMENT_NOT_READY``.
	"""
	row = _machine_row(equipment)
	if not row:
		return None
	# A-84: máy đang chạy test thì không nạp, kể cả đang mở khóa tạm
	running = open_run(equipment)
	if running:
		return Block(
			"EQUIPMENT_TESTING",
			_("Machine is running a test"),
			_("Machine {0} is running test {1}.").format(equipment, running.test_type),
			_("End the test and record its result, then load the machine."),
			object_type="Equipment",
			object_name=equipment,
		)
	# FEAT-052 A-71: HC-001/HC-003 không có mở khóa tạm, nên kiểm trước `unlock_until`
	block = chemical_lots.chemical_block(equipment, row.equipment_type)
	if block:
		return block
	unlocked = bool(row.unlock_until and get_datetime(row.unlock_until) > now_datetime())
	if _inspection_expired(row) and not (unlocked and row.equipment_type not in PRESSURE_TYPES):
		block = Block(
			"EQUIPMENT_INSPECTION_EXPIRED",
			_("Inspection has expired"),
			_("Equipment {0} was due for inspection on {1}.").format(
				equipment, frappe.utils.formatdate(row.inspection_due)
			),
			_("Use another machine. Call R02 about the inspection."),
			object_type="Equipment",
			object_name=equipment,
			error_code="TB-004" if row.equipment_type in PRESSURE_TYPES else None,
		)
		# máy áp lực: TB-004 khóa cứng; còn lại TB-002 theo cấu hình viện
		block = error_codes.check(block)
		if block:
			return block
	if _calibration_expired(row) and not unlocked:
		block = Block(
			"EQUIPMENT_CALIBRATION_EXPIRED",
			_("Calibration has expired"),
			_("Equipment {0} was due for calibration on {1}.").format(
				equipment, frappe.utils.formatdate(row.calibration_due)
			),
			_("Use another machine, or call R02 for a temporary unlock."),
			object_type="Equipment",
			object_name=equipment,
		)
		block = error_codes.check(block)
		if block:
			return block
	if unlocked:
		return None
	missing = missing_tests(equipment, row.equipment_type, row.daily_test_required)
	if missing:
		return Block(
			"DAILY_TEST_REQUIRED",
			_("Daily test is required"),
			_("Equipment {0} has no passed daily test today: {1}.").format(equipment, ", ".join(missing)),
			_("Record the daily test first, or call R02 for a temporary unlock."),
			items=missing,
			object_type="Equipment",
			object_name=equipment,
		)
	return None


def unlock_temp(equipment, reason, hours, station=None, client_ts=None):
	"""R02 mở khóa tạm máy (FR-M5-06.1): lý do và 1-24 giờ; trả ``{"equipment", "status", "unlock_until"}``.

	Máy Sửa chữa/Ngừng sử dụng, hoặc máy hấp (thiết bị áp lực) quá hạn kiểm định → UNLOCK_NOT_ALLOWED (FR-M5-06.2).
	Ghi Audit ``Override`` (``TempUnlock``). Quyền R02 do tầng RPC kiểm.
	"""
	if (
		isinstance(hours, bool)
		or not isinstance(hours, int | str)
		or not str(hours).strip().lstrip("-").isdigit()
	):
		raise _unlock_invalid(_("Enter the number of hours, from 1 to {0}.").format(MAX_UNLOCK_HOURS))
	hours = int(hours)
	if not 1 <= hours <= MAX_UNLOCK_HOURS:
		raise _unlock_invalid(_("Enter the number of hours, from 1 to {0}.").format(MAX_UNLOCK_HOURS))
	text = reason.strip() if isinstance(reason, str) else ""
	if not text or len(text) > MAX_REASON:
		raise _unlock_invalid(_("A reason of 1 to {0} characters is required.").format(MAX_REASON))
	machine = _equipment(equipment, for_update=True)
	if machine.status in ("Repair", "Retired") or (
		machine.equipment_type in PRESSURE_TYPES and _inspection_expired(machine)
	):
		raise _blocked(
			"UNLOCK_NOT_ALLOWED",
			_("Temporary unlock is not allowed"),
			_("Equipment {0} is {1} or has an overdue inspection of pressure equipment.").format(
				machine.name, _(machine.status, context="Equipment")
			),
			_("Use another machine. Nobody can unlock this one."),
		)
	until = add_to_date(now_datetime(), hours=hours)
	_apply(
		machine.name,
		status="Ready" if machine.status == "Locked" else None,
		unlock_until=until,
		unlocked_by=frappe.session.user,
		unlock_reason=text,
	)
	error_codes.allow_open(("TB-001", "TB-002"), "Equipment", machine.name, until, text)
	audit.log(
		"Override",
		"Equipment",
		machine.name,
		new={"event": "TempUnlock", "hours": hours, "reason": text},
		reason="TempUnlock",
		station=station,
		client_ts=client_ts,
	)
	return {"equipment": machine.name, "status": "Ready", "unlock_until": until}


def _unlock_invalid(reason):
	return _blocked(
		"UNLOCK_INVALID",
		_("Unlock request is not valid"),
		reason,
		_("Enter the reason and a duration of up to 24 hours."),
	)


def release_stale_locks():
	"""Mở máy đang khóa vì ``Daily Test`` mà không còn thiếu test bắt buộc nào (đổi cấu hình, patch; A-70); trả tên máy."""
	released = []
	for row in frappe.get_all(
		"Equipment",
		filters={"status": "Locked", "lock_reason": LOCK_DAILY_TEST},
		fields=["name", "equipment_type", "daily_test_required"],
	):
		if not missing_tests(row.name, row.equipment_type, row.daily_test_required):
			_apply(row.name, status="Ready", lock_reason=None)
			released.append(row.name)
	return released


def on_settings_update(doc=None, method=None):
	"""doc_events của TraceCore Settings: đổi chế độ có hiệu lực ngay với cả máy đang khóa (A-70)."""
	release_stale_locks()


def _open_runs(equipment, tests):
	"""``{loại test: Running | Ended}`` của lần chạy mới nhất chưa có kết quả."""
	runs = {}
	for test in tests:
		latest = _latest_run(equipment, test)
		if latest and latest.run_status in (RUN_RUNNING, RUN_ENDED) and not latest.result:
			runs[test] = latest.run_status
	return runs


def _station_types(station):
	"""Loại máy có test hằng ngày theo chức năng của trạm (A-85); trạm không rửa, không tiệt khuẩn → ``()``."""
	kinds = ()
	if zones.station_has_function(station, *WASH_FUNCTIONS):
		kinds += WASHERS
	if zones.station_has_function(station, *STERILIZER_FUNCTIONS):
		kinds += STERILIZERS
	return kinds


def overview(station=None, include=None):
	"""Máy có test hằng ngày và tình trạng hôm nay (cho màn SCR-23): ``required`` theo cấu hình, ``optional`` là tự nguyện.

	Có `station` thì chỉ máy theo chức năng của trạm; máy tiệt khuẩn chỉ khi thuộc diện bắt buộc, đang có lần chạy chưa đọc
	kết quả, hoặc là máy `include` vừa quét để ghi test tự nguyện (A-85).
	"""
	kinds = _station_types(station) if station else tuple(TESTS)
	if not kinds:
		return []
	rows = frappe.get_all(
		"Equipment",
		filters={"equipment_type": ["in", list(kinds)], "status": ["!=", "Retired"]},
		fields=[
			"name",
			"equipment_name",
			"equipment_type",
			"status",
			"lock_reason",
			"inspection_due",
			"calibration_due",
			"unlock_until",
			"unlocked_by",
			"unlock_reason",
			"daily_test_required",
		],
		order_by="equipment_type asc, name asc",
	)
	for row in rows:
		row["required"] = required_tests(row.equipment_type, row.daily_test_required)
		row["optional"] = [test for test in TESTS[row.equipment_type] if test not in row["required"]]
		row["missing"] = [test for test in row["required"] if not passed_today(row.name, test)]
		row["inspection_expired"] = _inspection_expired(row)
		row["calibration_expired"] = _calibration_expired(row)
		row["unlocked"] = bool(row.unlock_until and get_datetime(row.unlock_until) > now_datetime())
		row["unlocked_by_name"] = (
			frappe.utils.get_fullname(row.unlocked_by) if row["unlocked"] and row.unlocked_by else None
		)
		busy = unloaded_load(row.name)
		running = open_run(row.name)
		row["running_load"] = busy.name if busy else None
		row["running_status"] = busy.status if busy else None
		row["testing"] = running.test_type if running else None
		row["run_tests"] = [test for test in TESTS[row.equipment_type] if test in RUN_TESTS]
		row["runs"] = _open_runs(row.name, row["run_tests"])
		row["ready_to_load"] = cint(
			row.status == "Ready"
			and not busy
			and not running
			and not row["missing"]
			and not row["inspection_expired"]
			and not row["calibration_expired"]
		)
	if not station:
		return rows
	return [
		row
		for row in rows
		if row.equipment_type not in STERILIZERS or row["required"] or row["runs"] or row.name == include
	]
