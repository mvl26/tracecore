"""Lệnh cách ly và phòng cách ly theo khoa (FEAT-068; FR-M14-06, .1, FR-M14-07, .1; BRU-MDR-003; UC-52; A-146).

- `create_order` là đường duy nhất tạo `Isolation Order` (RPC SCR-60 WEB/DEPT): bắt buộc mã BN, loại phòng ngừa, lý do;
  ghi sổ ngay → Đang cách ly. Tạo từ chủng đa kháng: khoa và mã BN (đã mã hóa) chép ở server từ chủng, không qua trình
  duyệt; xong thì thông báo ``MDRO_DETECTED`` của chủng chuyển Đã đọc (A-146 Q4).
- Không chọn phòng hoặc phòng đã đủ giường → cách ly tại giường (``bedside_isolation``) + cảnh báo, không chặn (Q6).
- `close_order`: bắt buộc lý do kết thúc; lệnh do đa kháng chỉ R01/R11 đóng (BRU-MDR-003, FR-M14-06.1); R08/R12 chỉ
  khoa mình. `cancel_order` chỉ R01/R11 (nhập nhầm).
- Phòng cách ly: R01 tự đánh giá "đạt" (tiêu chí theo hướng dẫn bệnh viện, OQ-V12-08 — không mã hóa cứng); tỷ lệ khoa
  lâm sàng (`Department.tc_clinical`) có ≥ 1 phòng đạt và danh sách khoa chưa có (FR-M14-07, Q1, Q2).
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, get_datetime, getdate, now_datetime
from frappe.utils.password import get_decrypted_password

from tracecore.core import audit, notification, patient_code
from tracecore.core.errors import Block, BlockedError
from tracecore.microbiology import isolates, permissions

DOCTYPE = "Isolation Order"
ROOM_DOCTYPE = "Isolation Room"
DRAFT, OPEN, CLOSED, CANCELLED = "Draft", "Open", "Closed", "Cancelled"
REASON_MDRO = "Multidrug-Resistant Organism"
REASON_COMMUNICABLE = "Communicable Disease"
REASON_SUSPECTED = "Suspected Infection"
REASONS = (REASON_MDRO, REASON_COMMUNICABLE, REASON_SUSPECTED)
PRECAUTIONS = ("Contact", "Droplet", "Airborne", "Combined")
ROOM_TYPES = ("Single Room", "Negative Pressure Room", "Cohort Room")
ROOM_IN_USE, ROOM_FREE = "In Use", "Free"
OPENED_EVENT = "ISOLATION_ORDER_OPENED"
CLOSED_EVENT = "ISOLATION_ORDER_CLOSED"
MDRO_CLOSE_ROLES = ("TC R01", "TC R11")  # BRU-MDR-003: không cấp System Manager (quản trị IT)
CANCEL_ROLES = ("TC R01", "TC R11")
PORTAL_LINK = "/ksnk-khoa/cach-ly"
DESK_LINK = "/app/tc-ksnk/cach-ly"
MAX_TEXT = 500


def _block(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _text(value) -> str:
	return " ".join(cstr(value).split())[:MAX_TEXT]


def alert_link(isolate) -> str:
	"""Link của thông báo đa kháng: trang Cổng khoa tạo lệnh điền sẵn (R01/R11 được chuyển sang SCR-60 trên Desk)."""
	return f"{PORTAL_LINK}?isolate={isolate}"


# --- phòng cách ly ------------------------------------------------------------------------------------------------


def validate_room(doc):
	doc.room_code = "".join(cstr(doc.room_code).split()).upper()
	if cint(doc.beds) < 1:
		frappe.throw(_("An isolation room needs at least one bed."))
	if doc.checked_on and getdate(doc.checked_on) > getdate(now_datetime()):
		frappe.throw(_("Check date cannot be in the future."))
	if cint(doc.meets_standard) and not doc.checked_on:
		frappe.throw(_("Enter the check date of a room that meets the isolation standard."))
	if doc.checked_on and not cint(doc.meets_standard) and not _text(doc.standard_note):
		frappe.throw(_("Enter why the checked room does not meet the isolation standard."))


def _occupancy(room_names):
	if not room_names:
		return {}
	rows = frappe.get_all(
		DOCTYPE,
		filters={"isolation_room": ["in", list(room_names)], "docstatus": 1, "status": OPEN},
		fields=["isolation_room", "count(name) as occupied"],
		group_by="isolation_room",
	)
	return {row.isolation_room: cint(row.occupied) for row in rows}


def rooms(departments=None, include_disabled=False):
	"""Phòng cách ly (theo khoa) kèm số giường đang dùng, còn trống và trạng thái Đang dùng / Trống."""
	filters = {} if include_disabled else {"disabled": 0}
	if departments is not None:
		filters["department"] = ["in", list(departments) or [""]]
	rows = frappe.get_all(
		ROOM_DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"room_code",
			"department",
			"department_name",
			"room_type",
			"beds",
			"negative_pressure",
			"has_hand_sink",
			"has_anteroom",
			"meets_standard",
			"checked_on",
			"standard_note",
			"disabled",
		],
		order_by="department_name asc, room_code asc",
	)
	used = _occupancy([row.name for row in rows])
	for row in rows:
		row["occupied"] = used.get(row.name, 0)
		row["free"] = max(cint(row.beds) - row["occupied"], 0)
		row["state"] = ROOM_IN_USE if row["occupied"] else ROOM_FREE
	return rows


def _room_for(room, department, warnings):
	if not room:
		return None
	row = frappe.db.get_value(
		ROOM_DOCTYPE, room, ["department", "disabled", "beds", "room_code"], as_dict=True
	)
	if not row or row.department != department or cint(row.disabled):
		raise _block(
			"ISOLATION_ROOM_INVALID",
			_("Isolation room not valid"),
			_("Room {0} is not an active isolation room of this department.").format(
				(row and row.room_code) or room
			),
			_("Choose a room of this department, or leave the room empty for bedside isolation."),
		)
	if _occupancy([room]).get(room, 0) >= cint(row.beds):
		warnings.append(
			_("Room {0} is full; the patient is recorded as isolated at the bedside.").format(row.room_code)
		)
		return None
	return room


# --- tạo lệnh -----------------------------------------------------------------------------------------------------


def _isolate(name):
	row = frappe.db.get_value(
		isolates.DOCTYPE,
		name,
		[
			"name",
			"department",
			"department_name",
			"is_mdro",
			"mdro_flags",
			"mdro_rule_versions",
			"organism",
			"organism_name",
			"lab_sample_id",
			"patient_code_masked",
		],
		as_dict=True,
	)
	if not row:
		raise _block(
			"ISOLATION_ISOLATE_INVALID",
			_("Isolate not found"),
			_("Isolate {0} does not exist.").format(name),
			_("Open the order from the multidrug-resistant alert again, or enter the patient code."),
		)
	return row


def _rule_precaution(versions):
	for rule in cstr(versions).splitlines():
		value = frappe.db.get_value("MDRO Rule", rule.strip(), "precaution_type") if rule.strip() else None
		if value:
			return value
	return None


def prefill(isolate) -> dict:
	"""Giá trị điền sẵn của form tạo lệnh từ một chủng (không có mã BN rõ)."""
	row = _isolate(isolate)
	return {
		"isolate": row.name,
		"lab_sample_id": row.lab_sample_id,
		"department": row.department,
		"department_name": row.department_name or row.department,
		"patient_code_masked": row.patient_code_masked,
		"organism_name": row.organism_name or row.organism,
		"mdro_flags": row.mdro_flags,
		"is_mdro": cint(row.is_mdro),
		"reason": REASON_MDRO if cint(row.is_mdro) else "",
		"precaution_type": _rule_precaution(row.mdro_rule_versions) or "",
	}


def _start_at(value):
	moment = get_datetime(value) if value else now_datetime()
	if moment > now_datetime():
		raise _block(
			"ISOLATION_TIME_INVALID",
			_("Time not valid"),
			_("The isolation time cannot be in the future."),
			_("Check the date and time, then save again."),
		)
	return moment


def _required(values):
	if not cstr(values.get("patient_code")).strip():
		raise _block(
			"ISOLATION_PATIENT_REQUIRED",
			_("Patient code required"),
			_("An isolation order needs the patient code."),
			_("Enter the patient code (not the patient name), then create the order."),
		)
	if values.get("precaution_type") not in PRECAUTIONS:
		raise _block(
			"ISOLATION_PRECAUTION_REQUIRED",
			_("Isolation order not created"),
			_("The precaution type by route of transmission is required."),
			_("Choose Contact, Droplet, Airborne or Combined, then create the order."),
		)
	if values.get("reason") not in REASONS:
		raise _block(
			"ISOLATION_REASON_REQUIRED",
			_("Isolation order not created"),
			_("The reason for isolation is required."),
			_("Choose the reason, then create the order."),
		)


def create_order(values: dict):
	"""Tạo và ghi sổ một lệnh cách ly; trả Document (``flags.tc_warnings`` = cảnh báo không chặn)."""
	values = dict(values or {})
	source = None
	if values.get("isolate"):
		source = _isolate(values["isolate"])
		permissions.require_department(source.department)  # R08/R12 chỉ dùng chủng của khoa mình
		values["department"] = values.get("department") or source.department
		values["patient_code"] = get_decrypted_password(
			isolates.DOCTYPE, source.name, "patient_code", raise_exception=False
		)
	permissions.require_department(values.get("department"))
	_required(values)
	warnings = []
	room = _room_for(values.get("isolation_room"), values["department"], warnings)
	if not values.get("isolation_room"):
		warnings.append(_("No isolation room chosen; the patient is recorded as isolated at the bedside."))
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"patient_code": cstr(values["patient_code"]).strip()[:64],
			"department": values["department"],
			"isolation_room": room,
			"bedside_isolation": int(not room),
			"precaution_type": values["precaution_type"],
			"reason": values["reason"],
			"reason_detail": _text(values.get("reason_detail")) or None,
			"isolate": source.name if source else None,
			"start_at": _start_at(values.get("start_at")),
		}
	)
	doc.flags.tc_isolation = True
	doc.insert()
	doc.submit()
	doc.flags.tc_warnings = warnings
	return doc


# --- controller ---------------------------------------------------------------------------------------------------


def validate_order(doc):
	if doc.is_new() and not doc.flags.tc_isolation:
		frappe.throw(_("Isolation orders are created on the isolation screen."))
	patient_code.apply(doc)
	is_mdro = doc.reason == REASON_MDRO
	if doc.isolate and not is_mdro:
		is_mdro = bool(cint(frappe.db.get_value(isolates.DOCTYPE, doc.isolate, "is_mdro")))
	doc.is_mdro = int(is_mdro)
	if doc.docstatus == 0:
		doc.status = DRAFT
	elif doc.docstatus == 1 and doc.status in (None, "", DRAFT):
		doc.status = OPEN


def on_submit(doc):
	if doc.isolate:
		notification.resolve(isolates.MDRO_EVENT, isolates.DOCTYPE, doc.isolate)
	notification.emit(
		OPENED_EVENT,
		doc=doc,
		subject=_("Isolation order {0} opened in {1}").format(
			doc.name, doc.department_name or doc.department
		),
		message=_("Patient {0}: {1} precautions, reason {2}.").format(
			doc.patient_code_masked, _(doc.precaution_type), _(doc.reason)
		),
		link=f"{DESK_LINK}?order={doc.name}",
	)


def guard_after_submit(doc):
	if not doc.flags.tc_isolation_close:
		frappe.throw(_("Close the isolation order on the isolation screen with an end reason."))


def on_cancel(doc):
	doc.db_set("status", CANCELLED, update_modified=False)


# --- đóng / hủy ---------------------------------------------------------------------------------------------------


def can_close_mdro(user=None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(MDRO_CLOSE_ROLES))


def _open_doc(name):
	if not name or not frappe.db.exists(DOCTYPE, name):
		raise frappe.DoesNotExistError(_("Isolation order {0} does not exist.").format(name))
	doc = frappe.get_doc(DOCTYPE, name)
	permissions.require_department(doc.department)
	if doc.docstatus != 1 or doc.status != OPEN:
		raise _block(
			"ISOLATION_ALREADY_CLOSED",
			_("Isolation order already ended"),
			_("Isolation order {0} is {1}.").format(doc.name, _(doc.status)),
			_("Refresh the list of open isolation orders."),
		)
	return doc


def close_order(name, end_reason=None, end_at=None):
	"""Kết thúc lệnh cách ly (BRU-MDR-003)."""
	doc = _open_doc(name)
	reason = _text(end_reason)
	if not reason:
		raise _block(
			"ISOLATION_END_REASON_REQUIRED",
			_("Isolation order not closed"),
			_("The end reason is required to close an isolation order."),
			_("Enter why the isolation ends, then close the order."),
		)
	if cint(doc.is_mdro) and not can_close_mdro():
		raise _block(
			"ISOLATION_MDRO_CLOSE_DENIED",
			_("Isolation order not closed"),
			_(
				"An isolation order for a multidrug-resistant organism is closed by infection control staff only."
			),
			_("Ask the infection control supervisor to close this order."),
		)
	moment = get_datetime(end_at) if end_at else now_datetime()
	if moment > now_datetime() or moment < get_datetime(doc.start_at):
		raise _block(
			"ISOLATION_TIME_INVALID",
			_("Time not valid"),
			_("The end time must be between the start of isolation and now."),
			_("Check the date and time, then close again."),
		)
	doc.end_at = moment
	doc.end_reason = reason
	doc.closed_by = frappe.session.user
	doc.status = CLOSED
	doc.flags.tc_isolation_close = True
	doc.save(ignore_permissions=True)  # quyền khoa và vai trò đã kiểm ở trên
	notification.emit(
		CLOSED_EVENT,
		doc=doc,
		subject=_("Isolation order {0} closed in {1}").format(
			doc.name, doc.department_name or doc.department
		),
		message=_("Patient {0}: {1}").format(doc.patient_code_masked, reason),
		link=f"{DESK_LINK}?order={doc.name}",
	)
	return doc


def cancel_order(name, reason=None):
	"""Hủy lệnh nhập nhầm — chỉ R01/R11, bắt buộc lý do (ghi Audit Log)."""
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(CANCEL_ROLES):
		raise frappe.PermissionError(_("Only infection control staff can cancel an isolation order."))
	text = _text(reason)
	if not text:
		raise _block(
			"ISOLATION_END_REASON_REQUIRED",
			_("Isolation order not cancelled"),
			_("A reason is required to cancel an isolation order."),
			_("Enter why the order is cancelled."),
		)
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.docstatus != 1:
		raise _block(
			"ISOLATION_ALREADY_CLOSED",
			_("Isolation order already ended"),
			_("Isolation order {0} is {1}.").format(doc.name, _(doc.status)),
			_("Refresh the list of open isolation orders."),
		)
	doc.flags.ignore_permissions = True
	doc.cancel()
	audit.log("Cancel", DOCTYPE, doc.name, reason=text)
	doc.reload()
	return doc


# --- danh sách, tỷ lệ ---------------------------------------------------------------------------------------------

ORDER_FIELDS = (
	"name",
	"patient_code_masked",
	"patient_code_hash",
	"department",
	"department_name",
	"isolation_room",
	"bedside_isolation",
	"precaution_type",
	"reason",
	"reason_detail",
	"isolate",
	"is_mdro",
	"start_at",
	"status",
)


def open_orders(departments=None, limit=500):
	"""Lệnh đang cách ly (mới nhất trước) kèm số ngày, mã phòng, nhãn đa kháng đã từng có (FR-M14-05, so bằng hash)."""
	filters = {"docstatus": 1, "status": OPEN}
	if departments is not None:
		filters["department"] = ["in", list(departments) or [""]]
	rows = frappe.get_all(
		DOCTYPE, filters=filters, fields=list(ORDER_FIELDS), order_by="start_at desc", limit_page_length=limit
	)
	history = isolates.history_by_hash([row.patient_code_hash for row in rows])
	codes = dict(
		frappe.get_all(
			ROOM_DOCTYPE,
			filters={"name": ["in", [row.isolation_room for row in rows if row.isolation_room] or [""]]},
			fields=["name", "room_code"],
			as_list=True,
		)
	)
	today = getdate(now_datetime())
	for row in rows:
		row["mdro_history"] = history.get(row.pop("patient_code_hash"), [])
		row["room_code"] = codes.get(row.isolation_room)
		row["days"] = (today - getdate(row.start_at)).days + 1
	return rows


def clinical_departments(department=None):
	filters = {"tc_clinical": 1, "disabled": 0, "is_group": 0}
	if department:
		filters["name"] = department
	return frappe.get_all(
		"Department", filters=filters, fields=["name", "department_name"], order_by="department_name asc"
	)


def coverage(day=None, department=None) -> dict:
	"""Khoa lâm sàng có ≥ 1 phòng cách ly đạt (kiểm tra không muộn hơn ``day``) và danh sách khoa chưa có."""
	day = getdate(day or now_datetime())
	clinical = clinical_departments(department)
	names = [row.name for row in clinical]
	met = {}
	for row in frappe.get_all(
		ROOM_DOCTYPE,
		filters={
			"department": ["in", names or [""]],
			"disabled": 0,
			"meets_standard": 1,
			"checked_on": ["<=", day],
		},
		fields=["department", "room_code"],
	):
		met.setdefault(row.department, []).append(row.room_code)
	departments = [
		{
			"department": row.name,
			"department_name": row.department_name or row.name,
			"covered": bool(met.get(row.name)),
			"rooms": met.get(row.name, []),
		}
		for row in clinical
	]
	covered = sum(1 for row in departments if row["covered"])
	return {
		"day": str(day),
		"total": len(departments),
		"covered": covered,
		"rate": round(covered * 100.0 / len(departments), 1) if departments else None,
		"departments": departments,
		"missing": [row for row in departments if not row["covered"]],
	}
