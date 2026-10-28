"""Test hằng ngày và khóa máy (M5, FEAT-040; FR-M5-05 .1-.3, FR-M5-06 .1-.2; UC-23; BRU-EQP-001, BRU-EQP-002).

`record` ghi một Daily Test (Bowie-Dick, leak, test làm sạch máy rửa): Đạt mở máy cho ngày, Không đạt khóa máy và đánh
dấu NC chờ tạo (FEAT-030). `equipment_block` là hàm của hook ``tracecore_load_equipment_checks`` (T5) và
``tracecore_wash_equipment_checks`` (T2): chặn tạo mẻ/lô khi quá hạn kiểm định hoặc thiếu test ngày, M2 không import M5.
`unlock_temp` là mở khóa tạm của R02 (quyền kiểm ở RPC): lý do, 1-24 giờ, không với thiết bị áp lực quá hạn kiểm định.
Trạng thái máy chỉ đổi bằng cờ ``flags.tc_equipment`` (xem `equipment.py`).
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime, today

from tracecore.core import audit
from tracecore.core.errors import Block, BlockedError

# test bắt buộc theo loại máy; plasma không có test ngày (chỉ thị hóa học từng mẻ, FR-M5-05.2)
REQUIRED = {
	"Steam Sterilizer": ("bowie_dick", "leak"),
	"Washer-Disinfector": ("washer_cleaning",),
	"Ultrasonic Cleaner": ("washer_cleaning",),
}
RESULTS = ("Pass", "Fail")
PRESSURE_TYPES = (
	"Steam Sterilizer",
)  # thiết bị áp lực: quá hạn kiểm định thì không mở khóa tạm (FR-M5-06.2)
MAX_UNLOCK_HOURS = 24
MAX_REASON = 500
LOCK_DAILY_TEST = "Daily Test"
PHOTO_MISSING = "photo_missing"


def _blocked(code, title, reason, action, items=None):
	return BlockedError(Block(code, title, reason, action, items=items))


def required_tests(equipment_type):
	return list(REQUIRED.get(equipment_type, ()))


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
		{"equipment": equipment, "test_type": indicator, "test_date": getdate(on or today())},
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


def missing_tests(equipment, equipment_type):
	return [test for test in required_tests(equipment_type) if not passed_today(equipment, test)]


def _apply(equipment, status=None, **fields):
	"""Lưu trạng thái/trường khóa của máy (cờ ``tc_equipment``); máy Ngừng sử dụng hoặc Sửa chữa giữ nguyên trạng thái."""
	doc = frappe.get_doc("Equipment", equipment, for_update=True)
	if status and doc.status not in ("Retired", "Repair"):
		doc.status = status
	doc.update(fields)
	doc.flags.tc_equipment = True
	doc.save(ignore_permissions=True)
	return doc


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

	Loại test phải thuộc bộ test của loại máy, kết quả Đạt/Không đạt, lô test bắt buộc và còn hạn (E2). Thiếu ảnh
	Bowie-Dick chỉ cảnh báo ``photo_missing`` (UC-23 E3). Không đạt khóa máy (``lock_reason = Daily Test``) và đặt
	``nc_pending``; Đạt đủ bộ test của ngày thì mở lại máy đang bị khóa vì test.
	"""
	machine = _equipment(equipment, for_update=True)
	if test_type not in required_tests(machine.equipment_type):
		raise _invalid(
			_("Test {0} does not apply to {1}.").format(
				test_type, _(machine.equipment_type, context="Equipment")
			)
		)
	if result not in RESULTS:
		raise _invalid(_("The result must be Pass or Fail."))
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
	row = frappe.get_doc(
		{
			"doctype": "Daily Test",
			"equipment": machine.name,
			"test_type": test_type,
			"result": result,
			"test_date": today(),
			"lot": lot,
			"lot_expiry": lot_expiry,
			"photo": photo or None,
			"station": station,
			"tested_by_user": frappe.session.user,
			"tested_by": employee,
			"tested_at": now,
			"note": (note or "").strip()[:MAX_REASON] or None,
			"nc_pending": 1 if result == "Fail" else 0,
		}
	)
	row.flags.tc_daily_test = True
	row.insert(ignore_permissions=True)
	locked = unlocked = False
	if result == "Fail":
		if machine.status == "Ready":
			_apply(machine.name, status="Locked", lock_reason=LOCK_DAILY_TEST)
		locked = True
	elif (
		machine.status == "Locked"
		and machine.lock_reason == LOCK_DAILY_TEST
		and not missing_tests(machine.name, machine.equipment_type)
	):
		_apply(machine.name, status="Ready", lock_reason=None)
		unlocked = True
	return {
		"daily_test": row.name,
		"result": result,
		"locked": locked,
		"unlocked": unlocked,
		"warnings": [PHOTO_MISSING] if test_type == "bowie_dick" and not photo else [],
	}


def _inspection_expired(row):
	return bool(row.inspection_due and getdate(row.inspection_due) < getdate(today()))


def _calibration_expired(row):
	return bool(row.calibration_due and getdate(row.calibration_due) < getdate(today()))


def equipment_block(equipment):
	"""Hàm của hook ``tracecore_load_equipment_checks`` / ``tracecore_wash_equipment_checks``: Block hoặc None (FR-M5-06).

	Quá hạn kiểm định → ``EQUIPMENT_INSPECTION_EXPIRED``; quá hạn hiệu chuẩn → ``EQUIPMENT_CALIBRATION_EXPIRED`` (A-43 M5);
	thiếu test ngày → ``DAILY_TEST_REQUIRED`` kèm danh sách. Máy đang được R02 mở khóa tạm (``unlock_until`` chưa hết) bỏ
	qua test ngày và hiệu chuẩn quá hạn, và bỏ qua kiểm định quá hạn nếu không phải thiết bị áp lực. Máy
	``Locked``/``Repair`` đã bị chặn trước đó bởi ``EQUIPMENT_NOT_READY``.
	"""
	row = frappe.db.get_value(
		"Equipment",
		equipment,
		["equipment_type", "status", "inspection_due", "calibration_due", "unlock_until"],
		as_dict=True,
	)
	if not row:
		return None
	unlocked = bool(row.unlock_until and get_datetime(row.unlock_until) > now_datetime())
	if _inspection_expired(row) and not (unlocked and row.equipment_type not in PRESSURE_TYPES):
		return Block(
			"EQUIPMENT_INSPECTION_EXPIRED",
			_("Inspection has expired"),
			_("Equipment {0} was due for inspection on {1}.").format(
				equipment, frappe.utils.formatdate(row.inspection_due)
			),
			_("Use another machine. Call R02 about the inspection."),
		)
	if _calibration_expired(row) and not unlocked:
		return Block(
			"EQUIPMENT_CALIBRATION_EXPIRED",
			_("Calibration has expired"),
			_("Equipment {0} was due for calibration on {1}.").format(
				equipment, frappe.utils.formatdate(row.calibration_due)
			),
			_("Use another machine, or call R02 for a temporary unlock."),
		)
	if unlocked:
		return None
	missing = missing_tests(equipment, row.equipment_type)
	if missing:
		return Block(
			"DAILY_TEST_REQUIRED",
			_("Daily test is required"),
			_("Equipment {0} has no passed daily test today: {1}.").format(equipment, ", ".join(missing)),
			_("Record the daily test first, or call R02 for a temporary unlock."),
			items=missing,
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


def overview():
	"""Máy cần test hằng ngày và tình trạng hôm nay (cho màn SCR-23 và dashboard): danh sách ``dict``."""
	rows = frappe.get_all(
		"Equipment",
		filters={"equipment_type": ["in", list(REQUIRED)], "status": ["!=", "Retired"]},
		fields=[
			"name",
			"equipment_name",
			"equipment_type",
			"status",
			"lock_reason",
			"inspection_due",
			"calibration_due",
			"unlock_until",
		],
		order_by="equipment_type asc, name asc",
	)
	for row in rows:
		row["required"] = required_tests(row.equipment_type)
		row["missing"] = missing_tests(row.name, row.equipment_type)
		row["inspection_expired"] = _inspection_expired(row)
		row["calibration_expired"] = _calibration_expired(row)
		row["unlocked"] = bool(row.unlock_until and get_datetime(row.unlock_until) > now_datetime())
		row["ready_to_load"] = cint(
			row.status == "Ready"
			and not row["missing"]
			and not row["inspection_expired"]
			and not row["calibration_expired"]
		)
	return rows
