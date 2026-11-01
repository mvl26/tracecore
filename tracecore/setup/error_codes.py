"""Danh mục mã lỗi mặc định (FEAT-052, A-71): tạo khi cài app và sau migrate, không ghi đè bản ghi đã có.

Không dùng fixtures: `bench migrate` nhập lại fixtures với force, sẽ xóa hướng dẫn xử lý viện đã sửa (cùng lý do với
`setup.seed`). Chuỗi nguồn tiếng Anh, dịch ở vi.csv; hướng dẫn là bản nháp chờ khoa KSNK duyệt.

Chỉ TB-002, DC-001, HC-002, NS-002 đổi được mức độ hoặc tắt (người dùng chốt 31/10/2026); mã còn lại `severity_locked`.
"""

import frappe
from frappe import _

LOGIN = "LOGIN"
DIRTY = ("RECEIVE", "WASH_LOAD", "WASH_UNLOAD", "ASSEMBLE", "PACK")
AFTER_PACK = ("STERI_LOAD", "STERI_UNLOAD", "PUTAWAY", "ISSUE", "USE")
MACHINES = ("WASH_LOAD", "WASH_UNLOAD", "STERI_LOAD", "STERI_UNLOAD")


def _code(
	code,
	name,
	description,
	condition,
	stations,
	action,
	guide,
	block_codes=(),
	severity="Block",
	locked=True,
	release="Auto",
	warn_days=None,
	approvers=(),
):
	return {
		"code": code,
		"error_name": name,
		"description": description,
		"trigger_condition": condition,
		"stations": stations,
		"system_action": action,
		"guide": guide,
		"block_codes": block_codes,
		"default_severity": severity,
		"severity_locked": 1 if locked else 0,
		"release_method": release,
		"warn_days": warn_days,
		"approver_roles": approvers,
	}


DEFAULT_CODES = (
	_code(
		"HC-001",
		"Chemical lot has expired",
		"The chemical lot in use on the machine, or chosen for the batch, is past its expiry date.",
		"The declared lot, or the lot chosen when loading, has an expiry date before today.",
		("WASH_LOAD",),
		"Locks the machine for new batches and refuses to record the batch.",
		"<ol><li>Stop using the expired lot and set it aside.</li><li>Declare a valid lot on the machine.</li>"
		"<li>Scan the machine again. The lock clears on its own.</li></ol>",
		("CHEMICAL_LOT_EXPIRED",),
	),
	_code(
		"HC-002",
		"Chemical lot expires soon",
		"The chemical lot in use expires within the configured number of days.",
		"Days to expiry of the declared lot are at or below the configured limit.",
		("WASH_LOAD",),
		"Allows the operation and records a warning.",
		"<ol><li>Finish the current lot if possible.</li><li>Ask the stores for a replacement lot in time.</li></ol>",
		("CHEMICAL_LOT_EXPIRING",),
		severity="Warning",
		locked=False,
		warn_days=30,
	),
	_code(
		"HC-003",
		"Machine has no declared chemical lot",
		"The machine type needs a chemical lot, but no lot in use has been declared on the machine.",
		"The machine type requires a chemical lot and the machine has no declared lot.",
		("WASH_LOAD",),
		"Refuses to start a batch on the machine.",
		"<ol><li>Scan the lot of the chemical loaded on the machine.</li><li>Scan the machine again.</li></ol>",
		("EQUIPMENT_NO_CHEMICAL_LOT",),
	),
	_code(
		"HC-004",
		"Chemical or material lot is not valid",
		"The lot is disabled, has no expiry date, or does not belong to the required item.",
		"The scanned lot fails the check against the program or the item.",
		("WASH_LOAD", "PACK"),
		"Refuses the lot.",
		"<ol><li>Check the label of the lot.</li><li>Choose a lot of the item that the program uses.</li></ol>",
		("CHEMICAL_LOT_INVALID", "MAINT_OIL_LOT_REQUIRED"),
	),
	_code(
		"HC-005",
		"Stock lot has expired",
		"A manual stock issue chose a lot that is past its expiry date.",
		"The lot chosen for a manual issue has an expiry date before today.",
		("PACK",),
		"Refuses the stock issue.",
		"<ol><li>Choose a lot that is still valid.</li><li>Report the expired lot to the stores.</li></ol>",
		("LOT_EXPIRED",),
	),
	_code(
		"HC-006",
		"Laundry program does not disinfect",
		"Contaminated linen needs a hot enough program or a disinfectant.",
		"The program is below the required temperature and no disinfectant was added.",
		("WASH_LOAD",),
		"Refuses the laundry batch.",
		"<ol><li>Choose a hotter program, or add a disinfectant.</li><li>Record the batch again.</li></ol>",
		("LAUNDRY_TEMP_TOO_LOW",),
	),
	_code(
		"NS-001",
		"Certificate has expired",
		"A certificate required for this station is no longer valid.",
		"The employee has the station competency, but a required certificate has expired.",
		(LOGIN,),
		"Refuses the station login until the certificate is renewed or an approver allows temporary access.",
		"<ol><li>Renew the certificate and have it recorded.</li><li>If work cannot wait, ask an approver for "
		"temporary access. It is limited in time and the approver is recorded.</li></ol>",
		("CERTIFICATE_REQUIRED",),
		release="Approval",
		approvers=("TC R01", "TC R02"),
	),
	_code(
		"NS-002",
		"Certificate expires soon",
		"A certificate required for this station expires within the configured number of days.",
		"Days to expiry of a required certificate are at or below the configured limit.",
		(LOGIN,),
		"Allows the login, warns the employee and notifies the supervisor.",
		"<ol><li>Plan the renewal with your supervisor.</li><li>Record the new certificate when you receive it.</li></ol>",
		("CERTIFICATE_EXPIRING",),
		severity="Warning",
		locked=False,
		warn_days=30,
	),
	_code(
		"NS-003",
		"Not assigned to this station",
		"The employee has no active competency for this station.",
		"No active Station Competency matches the employee and the station at this time.",
		(LOGIN,),
		"Refuses the station login.",
		"<ol><li>Use a station you are assigned to.</li><li>Ask the supervisor to check the competency matrix.</li></ol>",
		("COMPETENCY_REQUIRED",),
	),
	_code(
		"NS-004",
		"Authorized person is required",
		"This step needs the confirmation of a person with the required role.",
		"The person confirming lacks the role, or the scanned card is not the signed-in employee.",
		(*DIRTY, *AFTER_PACK),
		"Refuses the step until an authorized person confirms it.",
		"<ol><li>Call the supervisor.</li><li>The supervisor confirms with card and PIN.</li></ol>",
		("R02_CONFIRM_REQUIRED", "APPROVER_NOT_ALLOWED", "CARD_MISMATCH"),
	),
	_code(
		"TB-001",
		"Daily test is required",
		"The machine has no passed daily test today.",
		"A required daily test for the machine has not passed today.",
		("WASH_LOAD", "STERI_LOAD"),
		"Refuses to load a batch on the machine.",
		"<ol><li>Run and record the daily test.</li><li>If work cannot wait, call the supervisor for a temporary "
		"unlock of up to 24 hours.</li></ol>",
		("DAILY_TEST_REQUIRED",),
		release="Approval",
	),
	_code(
		"TB-002",
		"Maintenance or calibration is overdue",
		"The machine is past its calibration or inspection date. Pressure equipment uses TB-004.",
		"The calibration or inspection due date of the machine is before today.",
		("WASH_LOAD", "STERI_LOAD"),
		"Blocks the machine, or warns when the hospital configured this code as a warning.",
		"<ol><li>Use another machine.</li><li>Arrange the service, then record it.</li><li>If work cannot wait, "
		"call the supervisor for a temporary unlock of up to 24 hours.</li></ol>",
		("EQUIPMENT_CALIBRATION_EXPIRED", "EQUIPMENT_INSPECTION_EXPIRED"),
		locked=False,
		release="Approval",
	),
	_code(
		"TB-003",
		"Machine is locked or out of service",
		"The machine is Locked, under Repair or Retired.",
		"The machine status is not Ready.",
		MACHINES,
		"Refuses to use the machine.",
		"<ol><li>Use another machine.</li><li>Call the supervisor to check why the machine is out of service.</li></ol>",
		("EQUIPMENT_NOT_READY", "EQUIPMENT_RETIRED", "UNLOCK_NOT_ALLOWED"),
	),
	_code(
		"TB-004",
		"Pressure equipment inspection has expired",
		"Pressure equipment past its legal inspection date must not run. Nobody can unlock it.",
		"A steam sterilizer has an inspection due date before today.",
		("STERI_LOAD",),
		"Locks the machine. No temporary unlock is possible.",
		"<ol><li>Use another machine.</li><li>Arrange the legal inspection.</li><li>Record the new inspection date.</li></ol>",
	),
	_code(
		"TB-005",
		"Wrong machine or program",
		"The machine does not fit this step, or the program does not belong to it.",
		"The scanned machine has the wrong type or differs from the batch, or the program is not on the machine.",
		MACHINES,
		"Refuses the machine or the program.",
		"<ol><li>Check the QR code on the machine.</li><li>Choose a program of that machine.</li></ol>",
		(
			"EQUIPMENT_NOT_WASHER",
			"EQUIPMENT_NOT_STERILIZER",
			"LAUNDRY_EQUIPMENT_INVALID",
			"EQUIPMENT_MISMATCH",
			"PROGRAM_INVALID",
			"LAUNDRY_PROGRAM_INVALID",
		),
	),
	_code(
		"TB-006",
		"Machine is busy or over capacity",
		"The machine has an unfinished load, or the load exceeds its capacity.",
		"A running load exists on the machine, or the load is above the machine capacity.",
		("WASH_LOAD", "STERI_LOAD"),
		"Refuses to add to the load.",
		"<ol><li>Finish the running load first.</li><li>Split the load if it is over capacity.</li></ol>",
		("EQUIPMENT_BUSY", "LOAD_CAPACITY_EXCEEDED", "LAUNDRY_OVER_CAPACITY"),
	),
	_code(
		"TB-007",
		"Daily test is running",
		"The machine is running a daily test, or the test has not ended yet.",
		"A test run has started on the machine and has not ended, or a result is entered before the run ends.",
		("WASH_LOAD", "STERI_LOAD"),
		"Refuses to load the machine and to record the result.",
		"<ol><li>Let the test finish and end it on the Daily test tab.</li><li>Read and record the result.</li></ol>",
		("EQUIPMENT_TESTING", "DAILY_TEST_RUN_OPEN", "DAILY_TEST_RUN_NOT_ENDED"),
	),
	_code(
		"CT-001",
		"Load indicator did not pass",
		"A chemical or biological indicator of the load failed or is pending, or the pack was recalled.",
		"The load has a failed cycle or indicator, is awaiting its biological indicator, or its packs were recalled.",
		("STERI_UNLOAD", "PUTAWAY", "ISSUE", "USE"),
		"Refuses sterile storage, issue and use of packs in the load.",
		"<ol><li>Do not use the packs.</li><li>Set them aside and call the supervisor.</li>"
		"<li>Follow the reprocessing or recall procedure.</li></ol>",
		("LOAD_NOT_RELEASABLE", "PACK_RECALLED"),
	),
	_code(
		"CT-002",
		"Indicator or test lot has expired",
		"The indicator or test lot is past its expiry date.",
		"The scanned lot has an expiry date before the day of use.",
		("PACK", "WASH_UNLOAD", "STERI_LOAD"),
		"Refuses the lot.",
		"<ol><li>Stop using the expired lot.</li><li>Scan a lot that is still valid.</li></ol>",
		("CI_LOT_EXPIRED", "TEST_LOT_EXPIRED", "INDICATOR_EXPIRED"),
	),
	_code(
		"CT-003",
		"Indicator or test is not valid",
		"The indicator or test does not fit the method, or its required details are missing.",
		"The class, method or details of the indicator fail the check.",
		("PACK", "WASH_UNLOAD", "STERI_LOAD", "STERI_UNLOAD"),
		"Refuses the indicator or test.",
		"<ol><li>Check the indicator type against the sterilization method.</li><li>Enter the missing details.</li></ol>",
		(
			"CI_LOT_INVALID",
			"INDICATOR_INVALID",
			"TEST_INVALID",
			"INDICATOR_REQUIRED",
			"INDICATOR_LOT_MISSING",
			"INDICATOR_LOT_INVALID",
			"INDICATOR_PHOTO_MISSING",
		),
	),
	_code(
		"DC-001",
		"Set is missing instruments",
		"Instruments in the set do not match the bill of materials.",
		"Lines are short and unconfirmed at assembly.",
		("ASSEMBLE",),
		"Blocks the step, or warns when the hospital configured this code as a warning.",
		"<ol><li>Count the set again.</li><li>Add what is missing, or call the supervisor to confirm the shortage.</li></ol>",
		("SHORTAGE_UNCONFIRMED",),
		locked=False,
	),
	_code(
		"DC-002",
		"Pack sterility has expired",
		"The pack is past its sterile expiry date.",
		"The pack expiry date is before today.",
		AFTER_PACK,
		"Refuses loading, storage, issue and use of the pack.",
		"<ol><li>Do not use the pack.</li><li>Send it back to the dirty zone for reprocessing.</li></ol>",
		("PACK_EXPIRED",),
	),
	_code(
		"DC-003",
		"Instrument maintenance is overdue",
		"An instrument in the set needs maintenance that can no longer be deferred.",
		"The instrument cycle counter passed the maintenance limit.",
		("PACK",),
		"Refuses to pack the set.",
		"<ol><li>Maintain the instrument.</li><li>Confirm the maintenance as done.</li></ol>",
		("MAINT_OVERDUE", "MAINT_ACTION_REQUIRED"),
	),
	_code(
		"DC-004",
		"Set reached its reprocessing limit",
		"The set or an instrument reached its cycle limit, or the department is above its par level.",
		"The cycle count reached the limit, or the issue exceeds the par level without approval.",
		("PACK", "ISSUE", "USE"),
		"Refuses the step until an approved override exists.",
		"<ol><li>Stop using the set.</li><li>Ask the supervisor to request an override or to dispose of the set.</li></ol>",
		("PAR_EXCEEDED", "SET_END_OF_LIFE", "PAR_APPROVAL_REQUIRED"),
	),
	_code(
		"DC-005",
		"Pack cannot be used at this step",
		"The pack does not fit the load, is already used, voided or in another document.",
		"The pack status, its method or its document does not allow this step.",
		AFTER_PACK,
		"Refuses the pack.",
		"<ol><li>Check the pack label and status.</li><li>Use another pack, or call the supervisor.</li></ol>",
		(
			"PACK_INCOMPATIBLE",
			"PACK_NOT_LOADABLE",
			"PACK_IN_OTHER_LOAD",
			"PACK_IN_OTHER_ISSUE",
			"PACK_USED",
			"PACK_VOID",
			"PACK_NOT_ISSUED",
		),
	),
	_code(
		"DC-006",
		"Test program cannot take packs",
		"Bowie-Dick, leak and vacuum test programs run without instrument packs.",
		"A pack is scanned or a load is completed with a test program of the sterilizer.",
		("STERI_LOAD",),
		"Refuses the pack and the load.",
		"<ol><li>Choose a sterilization program of the machine.</li><li>Run the test from the Daily test tab, "
		"without instrument packs.</li></ol>",
		("PROGRAM_TEST_ONLY",),
	),
	_code(
		"QT-001",
		"Wrong station order",
		"The set or pack is not at the right step for this station.",
		"A previous gate has not passed, or the status does not fit this station.",
		(*DIRTY, *AFTER_PACK),
		"Refuses the scan at this station.",
		"<ol><li>Check the step the set is at.</li><li>Take it to that station, or redo the step shown.</li></ol>",
		(
			"GATE_PREV_NOT_PASSED",
			"STATUS_INVALID_FOR_STATION",
			"STATION_WRONG_STEP",
			"STEP_ALREADY_PASSED",
			"ACTIVE_CYCLE_EXISTS",
			"SET_IN_OTHER_BATCH",
			"BATCH_NOT_RUNNING",
			"LOAD_NOT_OPEN",
			"PACK_NOT_RELEASED",
			"PACK_NOT_IN_STOCK",
		),
	),
	_code(
		"QT-002",
		"Step data is incomplete",
		"The step cannot finish because required data is missing.",
		"Lines are uncounted, the set has no bill of materials, or cycle data is incomplete.",
		(*DIRTY, "STERI_LOAD", "STERI_UNLOAD"),
		"Refuses to finish the step.",
		"<ol><li>Complete the items listed in the message.</li><li>Finish the step again.</li></ol>",
		(
			"BOM_INCOMPLETE",
			"LINES_NOT_COUNTED",
			"LINE_VARIANCE_REQUIRED",
			"DATA_INCOMPLETE",
			"CYCLE_DATA_OUT_OF_RANGE",
		),
	),
	_code(
		"QT-003",
		"Reason or patient code is required",
		"This exception needs a reason, or the patient code must be recorded.",
		"An earlier pack was skipped, the department differs, a receipt is incomplete, or the patient code is missing.",
		("RECEIVE", "ISSUE", "USE"),
		"Refuses the step until the reason or the code is entered.",
		"<ol><li>Enter the reason or the patient code.</li><li>Confirm the step again.</li></ol>",
		(
			"FEFO_NOTE_REQUIRED",
			"RECIPIENT_DEPT_MISMATCH",
			"DEPARTMENT_REASON_REQUIRED",
			"PATIENT_CODE_REQUIRED",
			"PATIENT_CODE_DEADLINE",
			"CONFIRM_INCOMPLETE",
		),
	),
)


def _insert(row):
	doc = frappe.get_doc(
		{
			"doctype": "TraceCore Error Code",
			"code": row["code"],
			"error_group": row["code"][:2],
			"error_name": _(row["error_name"], "vi"),
			"description": _(row["description"], "vi"),
			"trigger_condition": _(row["trigger_condition"], "vi"),
			"system_action": _(row["system_action"], "vi"),
			"guide": _(row["guide"], "vi"),
			"default_severity": row["default_severity"],
			"severity_locked": row["severity_locked"],
			"release_method": row["release_method"],
			"block_codes": "\n".join(row["block_codes"]),
			"stations": [{"station_key": key} for key in row["stations"]],
		}
	)
	doc.insert(ignore_permissions=True)


def ensure_error_codes() -> None:
	"""Thêm mã và dòng cấu hình còn thiếu; bản ghi đã có (kể cả viện đã sửa) giữ nguyên."""
	for row in DEFAULT_CODES:
		if not frappe.db.exists("TraceCore Error Code", row["code"]):
			_insert(row)
	settings = frappe.get_doc("TraceCore Settings")
	existing = {rule.error_code for rule in settings.error_rules}
	missing = [row for row in DEFAULT_CODES if row["code"] not in existing]
	for row in missing:
		settings.append(
			"error_rules",
			{
				"error_code": row["code"],
				"enabled": 1,
				"severity": row["default_severity"],
				"warn_days": row["warn_days"],
				"approver_roles": "\n".join(row["approver_roles"]),
			},
		)
	if missing:
		settings.save(ignore_permissions=True)
