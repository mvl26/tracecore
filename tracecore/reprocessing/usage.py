"""Quét sử dụng gói tại khoa (T8, FEAT-027; FR-M2-17 .1-.4, FR-M2-18 .1-.3; UC-13; BRU-ID-003, BRU-REP-010).

R08 quét Cycle ID, nhập mã bệnh nhân, mã ca mổ, phẫu thuật viên, phòng: `confirm` tạo Usage Record (ghi sổ), Pack sang
``Used`` (Cycle ID hết hiệu lực, không kích hoạt lại) và Set Unit sang Chờ tiếp nhận qua `step_gate.use_pack`. Mã
không dùng được (Đã dùng, Thu hồi, Hết hiệu lực, Quá hạn, chưa cấp phát, bộ hết vòng đời) bị chặn kèm lý do và ngày.

Mã bệnh nhân chỉ nằm ở trường Password của Usage Record: không vào Audit Log, log hay kết quả trả về; `reveal` trả mã
rõ cho R01/R02 (quyền kiểm ở tầng RPC) và ghi Audit ``View Patient Code`` kèm lý do.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, formatdate, getdate, now_datetime, today
from frappe.utils.password import get_decrypted_password

from tracecore.core import audit, gs1, step_gate
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import storage

STEP = "T8"
ISSUED = "Issued"
USED = "Used"
EMERGENCY_HOURS = 24  # FR-M2-17.2
SAVEPOINT = "tc_usage_confirm"
MAX_CODE = 50
MAX_NAME = 140
MAX_REASON = 500


def _blocked(code, title, reason, action, items=None):
	return BlockedError(Block(code, title, reason, action, items=items))


def _require_station(station):
	"""Trạm (không phải khu) của bước T8; ngược lại STATION_WRONG_STEP."""
	row = (
		frappe.db.get_value("Zone Station", station, ["is_zone", "station_step"], as_dict=True)
		if station
		else None
	)
	if row and not cint(row.is_zone) and row.station_step == STEP:
		return
	raise _blocked(
		"STATION_WRONG_STEP",
		_("Wrong station"),
		_("{0} is not a {1} usage station.").format(station, STEP)
		if row
		else _("Station {0} does not exist.").format(station or "-"),
		_("Open the usage screen on a T8 station in a department."),
	)


def _scanner_department(employee):
	return frappe.db.get_value("Employee", employee, "department") if employee else None


def _pack_department(pack):
	"""Khoa nhận gói: phiếu cấp phát đã ghi sổ gần nhất chứa gói; không có thì khoa của chính Pack."""
	rows = frappe.db.sql(
		"""select note.department from `tabIssue Note Pack` row
		join `tabIssue Note` note on note.name = row.parent
		where row.pack = %s and note.docstatus = 1 order by note.creation desc limit 1""",
		pack.name,
	)
	return rows[0][0] if rows else pack.department


def _date(value):
	return formatdate(getdate(value))


def _used_on(pack):
	used_at = frappe.db.get_value("Usage Record", {"pack": pack.name, "docstatus": 1}, "used_at")
	return _date(used_at or pack.modified)


def _check_usable(pack, on=None):
	"""FR-M2-18: chặn 100 % Cycle ID không còn dùng được, kèm lý do và ngày phát sinh trạng thái (không có ngoại lệ).

	`on`: ngày sử dụng để so hạn dùng (giao dịch offline phát lại, A-40); mặc định hôm nay.
	"""
	status = pack.status
	if status == USED:
		raise _blocked(
			"PACK_USED",
			_("Pack already used"),
			_("Cycle ID {0} was used on {1} and is no longer valid.").format(pack.name, _used_on(pack)),
			_("Do not use this pack. Return it to the dirty zone; a used Cycle ID is never reactivated."),
		)
	if status == "Recalled":
		raise _blocked(
			"PACK_RECALLED",
			_("Pack recalled"),
			_("Cycle ID {0} was recalled on {1}.").format(pack.name, _date(pack.modified)),
			_("Do not use this pack. Return it to the sterile store and call R02."),
		)
	if status == "Void" and pack.void_reason == "Expired":
		raise _blocked(
			"PACK_EXPIRED",
			_("Pack has expired"),
			_("Pack {0} expired on {1}.").format(pack.name, _date(pack.expiry)),
			_("Do not use this pack; send it back to the dirty zone."),
		)
	if status == "Void":
		raise _blocked(
			"PACK_VOID",
			_("Cycle ID no longer valid"),
			_("Cycle ID {0} became invalid on {1} ({2}).").format(
				pack.name, _date(pack.modified), _(pack.void_reason or "Void", context="Pack")
			),
			_("Do not use this pack; call R02 if you think this is a mistake."),
		)
	if status != ISSUED:
		raise _blocked(
			"PACK_NOT_ISSUED",
			_("Pack was not issued to a department"),
			_("Pack {0} is {1}; only an issued pack can be used.").format(
				pack.name, _(status, context="Pack")
			),
			_("Do not use this pack; ask the sterile store to issue it first."),
		)
	if getdate(pack.expiry) < getdate(on or today()):
		raise _blocked(
			"PACK_EXPIRED",
			_("Pack has expired"),
			_("Pack {0} expired on {1}.").format(pack.name, _date(pack.expiry)),
			_("Do not use this pack; send it back to the dirty zone."),
		)
	set_status = frappe.db.get_value("Set Unit", pack.set_unit, "status")
	if set_status == "End of Life":
		raise _blocked(
			"SET_END_OF_LIFE",
			_("Set has used up its cycles"),
			_("Set {0} reached its cycle limit and cannot be used.").format(pack.set_unit),
			_("Do not use this pack; call R02 or R01 about an override."),
		)
	if set_status != "At Department":
		raise _blocked(
			"STATUS_INVALID_FOR_STATION",
			_("Set status does not match this station"),
			_("Set {0} is {1}; station {2} accepts only sets that are {3}.").format(
				pack.set_unit,
				_(set_status, context="Set Unit"),
				STEP,
				_("At Department", context="Set Unit"),
			),
			_("Check the set status, or call R02."),
		)


def _pack_for_scan(raw):
	cycle_id = storage._scan(
		raw, "pack", _("Not a pack code"), _("Scan the DataMatrix or the Cycle ID on the pack label.")
	)
	return frappe.get_doc("Pack", storage._pack_name(cycle_id))


def _surgery_packs(surgery_code):
	if not surgery_code:
		return []
	return frappe.get_all(
		"Usage Record",
		filters={"surgery_code": surgery_code, "docstatus": 1},
		pluck="pack",
		order_by="creation",
	)


def _card(pack, employee):
	pack_department = _pack_department(pack)
	scanner_department = _scanner_department(employee)
	return {
		"cycle_id": pack.name,
		"set_id": pack.set_unit,
		"set_type": pack.set_type,
		"set_name": pack.set_name,
		"method": pack.method,
		"expiry": getdate(pack.expiry),
		"pack_department": pack_department,
		"scanner_department": scanner_department,
		"department_mismatch": bool(
			pack_department and scanner_department and pack_department != scanner_department
		),
	}


def scan(raw, station, employee=None):
	"""Quét Cycle ID ở màn T8: kiểm hiệu lực (FR-M2-18) rồi trả thẻ gói kèm cảnh báo khác khoa (FR-M2-17.4).

	Chỉ đọc. Mã không phải gói → SCAN_INVALID; không có gói → PACK_NOT_FOUND; Cycle ID không dùng được → các mã
	``PACK_USED``, ``PACK_RECALLED``, ``PACK_VOID``, ``PACK_EXPIRED``, ``PACK_NOT_ISSUED``, ``SET_END_OF_LIFE``.
	"""
	_require_station(station)
	pack = _pack_for_scan(raw)
	_check_usable(pack)
	return _card(pack, employee)


def _text(value, limit, code, title, reason, action):
	text = value.strip() if isinstance(value, str) else ""
	if not text or len(text) > limit:
		raise _blocked(code, title, reason, action)
	return text


def _optional(value, limit):
	text = value.strip() if isinstance(value, str) else ""
	return text[:limit]


def confirm(
	cycle_id,
	station,
	employee,
	patient_code=None,
	surgery_code=None,
	surgeon=None,
	room=None,
	emergency=False,
	department_reason=None,
	client_ts=None,
	used_at=None,
):
	"""Xác nhận sử dụng một gói (FR-M2-17): Usage Record ghi sổ, Pack → Used, Set Unit → Chờ tiếp nhận.

	`used_at` (giờ hệ thống): thời điểm nghiệp vụ của giao dịch offline phát lại (ADR-003, A-40); hạn dùng so theo
	ngày đó. Không truyền → giờ server hiện tại như trước.

	Mã bệnh nhân bắt buộc (1-50 ký tự), trừ ca cấp cứu: lưu trống và nhập bổ sung trong 24 giờ (`set_patient_code`).
	Mã ca mổ bắt buộc; nhiều gói cùng mã ca mổ được. Gói thuộc khoa khác khoa người quét cần lý do. Mọi ghi trong một
	savepoint. Trả ``{"usage", "cycle_id", "set_id", "patient_code_masked", "emergency", "patient_code_due",
	"surgery_packs"}``; không trả mã rõ.
	"""
	_require_station(station)
	emergency = bool(cint(emergency))
	if not emergency:
		patient_code = _text(
			patient_code,
			MAX_CODE,
			"PATIENT_CODE_REQUIRED",
			_("Patient code is required"),
			_("Enter the patient code, 1 to {0} characters.").format(MAX_CODE),
			_("Enter the patient code, or choose Emergency to enter it within 24 hours."),
		)
	else:
		patient_code = _optional(patient_code, MAX_CODE)
	surgery_code = _text(
		surgery_code,
		MAX_CODE,
		"DATA_INCOMPLETE",
		_("Surgery code is required"),
		_("Enter the surgery code, 1 to {0} characters.").format(MAX_CODE),
		_("Enter the surgery code, then confirm again."),
	)
	frappe.db.savepoint(SAVEPOINT)
	try:
		pack = storage._lock_pack(storage._pack_name(cycle_id))
		_check_usable(pack, getdate(used_at) if used_at else None)
		card = _card(pack, employee)
		reason = _optional(department_reason, MAX_REASON)
		if card["department_mismatch"] and not reason:
			raise _blocked(
				"DEPARTMENT_REASON_REQUIRED",
				_("Pack belongs to another department"),
				_("Pack {0} was issued to {1}, not to {2}.").format(
					pack.name, card["pack_department"], card["scanner_department"]
				),
				_("Enter why this department uses the pack, then confirm again."),
			)
		now = used_at or now_datetime()
		record = frappe.get_doc(
			{
				"doctype": "Usage Record",
				"pack": pack.name,
				"set_unit": pack.set_unit,
				"set_type": pack.set_type,
				"department": card["scanner_department"] or card["pack_department"],
				"pack_department": card["pack_department"],
				"department_reason": reason if card["department_mismatch"] else None,
				"used_at": now,
				"client_ts": client_ts,
				"station": station,
				"scanned_by_user": frappe.session.user,
				"scanned_by": employee,
				"patient_code": patient_code or None,
				"emergency": 1 if emergency else 0,
				"patient_code_due": add_to_date(now, hours=EMERGENCY_HOURS) if emergency else None,
				"surgery_code": surgery_code,
				"surgeon": _optional(surgeon, MAX_NAME),
				"room": _optional(room, MAX_CODE),
			}
		)
		record.flags.tc_usage = True
		record.insert(ignore_permissions=True)
		record.submit()
		pack.update({"status": USED})
		storage._save(pack)
		step_gate.use_pack(pack.set_unit)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return {
		"usage": record.name,
		"cycle_id": pack.name,
		"set_id": pack.set_unit,
		"patient_code_masked": record.patient_code_masked,
		"emergency": bool(record.emergency),
		"patient_code_due": record.patient_code_due,
		"surgery_packs": _surgery_packs(surgery_code),
	}


def _usage(name, for_update=False):
	if not name or not frappe.db.exists("Usage Record", {"name": name, "docstatus": 1}):
		raise _blocked(
			"USAGE_NOT_FOUND",
			_("Usage record not found"),
			_("Usage record {0} does not exist.").format(name or "-"),
			_("Check the usage record number, or call R02."),
		)
	return frappe.get_doc("Usage Record", name, for_update=for_update)


def set_patient_code(usage, patient_code, employee=None):
	"""Nhập bổ sung mã bệnh nhân của ca cấp cứu trong 24 giờ sau khi quét (FR-M2-17.2, BRU-REP-010 ngoại lệ)."""
	record = _usage(usage, for_update=True)
	if get_decrypted_password("Usage Record", record.name, "patient_code", raise_exception=False):
		raise _blocked(
			"PATIENT_CODE_ALREADY_SET",
			_("Patient code already entered"),
			_("Usage record {0} already has a patient code.").format(record.name),
			_("The patient code cannot be changed; call R02 if it is wrong."),
		)
	if not cint(record.emergency) or (record.patient_code_due and record.patient_code_due < now_datetime()):
		raise _blocked(
			"PATIENT_CODE_DEADLINE",
			_("Patient code deadline passed"),
			_("The patient code of usage record {0} can no longer be entered.").format(record.name),
			_("Call R02 to record the patient code."),
		)
	code = _text(
		patient_code,
		MAX_CODE,
		"PATIENT_CODE_REQUIRED",
		_("Patient code is required"),
		_("Enter the patient code, 1 to {0} characters.").format(MAX_CODE),
		_("Enter the patient code, then confirm again."),
	)
	record.flags.tc_usage = True
	record.patient_code = code
	record.save(ignore_permissions=True)
	return {"usage": record.name, "patient_code_masked": record.patient_code_masked}


def reveal_patient_code(usage, reason):
	"""Mã bệnh nhân rõ cho R01/R02 (quyền kiểm ở RPC); lý do bắt buộc, ghi Audit ``View Patient Code`` không chứa mã."""
	record = _usage(usage)
	text = _text(
		reason,
		MAX_REASON,
		"REASON_REQUIRED",
		_("Reason is required"),
		_("A reason of 1 to {0} characters is required to view the patient code.").format(MAX_REASON),
		_("Enter why you need the full patient code."),
	)
	code = get_decrypted_password("Usage Record", record.name, "patient_code", raise_exception=False) or ""
	audit.log("View Patient Code", "Usage Record", record.name, reason=text)
	return code
