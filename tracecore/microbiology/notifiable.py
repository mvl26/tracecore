"""Khai báo bệnh truyền nhiễm (FEAT-069; FR-M14-10, .1; BRU-MDR-005, BRU-HAI-005; UC-53 bước 5-6, E2, E3; A-150 Q1,
Q5, Q6).

- TraceCore không thay nghĩa vụ khai báo trên hệ thống giám sát quốc gia; chỉ theo dõi đã khai báo hay chưa
  (``reported_on`` + ``report_ref``, BRU-MDR-005).
- Hạn khai báo = ``diagnosed_on`` + số giờ của nhóm bệnh A/B/C trong `IC Program Settings` (chuyên gia pháp chế nhập —
  OQ-V12-03, không mã hóa cứng). Nhóm chưa cấu hình → không tính ``due_by``, cảnh báo và báo R01/R10 (E2).
- `create_report` là đường duy nhất tạo `Notifiable Disease Report` (ghi sổ ngay); R08/R12 chỉ khoa mình.
- `remind` (job 15 phút): nhắc R11 + R08 của khoa một lần khi qua nửa thời hạn, một lần khi quá hạn, rồi mỗi ngày một
  lần đến khi có cả ``reported_on`` và ``report_ref`` (Q6, E3).
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, cstr, flt, get_datetime, getdate, now_datetime

from tracecore.core import audit, notification, patient_code
from tracecore.core.errors import Block, BlockedError
from tracecore.microbiology import isolates, permissions

DOCTYPE = "Notifiable Disease Report"
DISEASE_DOCTYPE = "Communicable Disease"
SETTINGS = "IC Program Settings"
GROUPS = ("A", "B", "C")
DRAFT, PENDING, REPORTED, CANCELLED = "Draft", "Pending", "Reported", "Cancelled"
# trạng thái hiển thị (tính khi đọc)
STATE_WAITING, STATE_OVERDUE, STATE_MISSING_REF = "Awaiting report", "Overdue", "Reference missing"
STATE_REPORTED, STATE_LATE, STATE_NO_DEADLINE = "Reported", "Reported late", "No deadline configured"
STATE_CANCELLED = "Cancelled"
EVENT = "NOTIFIABLE_DUE"
CONFIG_EVENT = "NOTIFIABLE_CONFIG_MISSING"
IC_ROLE = "TC R11"
CANCEL_ROLES = ("TC R01", "TC R11")
WRITE_ROLES = ("TC R01", "TC R08", "TC R11", "TC R12", "System Manager")
DESK_LINK = "/app/tc-ksnk/o-dich"
PORTAL_LINK = "/ksnk-khoa/khai-bao"
STAGE_NONE, STAGE_HALF, STAGE_OVERDUE = 0, 1, 2
MAX_TEXT = 140
LIST_FIELDS = (
	"name",
	"patient_code_masked",
	"department",
	"department_name",
	"disease",
	"disease_name",
	"disease_group",
	"diagnosed_on",
	"due_by",
	"deadline_hours",
	"reported_on",
	"report_ref",
	"reported_late",
	"status",
	"outbreak_investigation",
)


def _block(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _text(value, limit=MAX_TEXT) -> str:
	return " ".join(cstr(value).split())[:limit]


# --- danh mục, thời hạn -------------------------------------------------------------------------------------------


def validate_disease(doc):
	doc.disease_code = "".join(cstr(doc.disease_code).split()).upper()
	doc.disease_name = _text(doc.disease_name)
	if doc.disease_group not in GROUPS:
		frappe.throw(_("Choose disease group A, B or C."))


def deadline_hours(group):
	"""Số giờ khai báo của nhóm bệnh (None = chưa cấu hình, FR-M14-10.1)."""
	if group not in GROUPS:
		return None
	value = frappe.db.get_single_value(SETTINGS, f"notifiable_hours_{group.lower()}")
	return flt(value) if value and flt(value) > 0 else None


def diseases():
	return frappe.get_all(
		DISEASE_DOCTYPE,
		filters={"disabled": 0},
		fields=["name", "disease_name", "disease_group"],
		order_by="disease_group asc, disease_name asc",
	)


def missing_groups():
	return [group for group in GROUPS if deadline_hours(group) is None]


# --- tạo ----------------------------------------------------------------------------------------------------------


def _disease(name):
	row = (
		frappe.db.get_value(DISEASE_DOCTYPE, name, ["name", "disease_group", "disabled"], as_dict=True)
		if name
		else None
	)
	if not row or cint(row.disabled):
		raise _block(
			"NOTIFIABLE_DISEASE_REQUIRED",
			_("Disease required"),
			_("Choose an active disease from the communicable disease list."),
			_("Ask the head of infection control to add the disease to the list if it is missing."),
		)
	return row


def _moment(value, earliest=None):
	moment = get_datetime(value) if value else None
	if not moment or moment > now_datetime() or (earliest and moment < get_datetime(earliest)):
		raise _block(
			"NOTIFIABLE_DATE_INVALID",
			_("Date not valid"),
			_("The date and time are required, cannot be in the future, and cannot be before the diagnosis."),
			_("Check the date and time, then save again."),
		)
	return moment


def create_report(values: dict):
	"""Ghi và ghi sổ một ca bệnh truyền nhiễm phải khai báo; trả Document (``flags.tc_warnings``)."""
	values = dict(values or {})
	permissions.require_department(values.get("department"), code="NOTIFIABLE_NOT_ALLOWED")
	if not cstr(values.get("patient_code")).strip():
		raise _block(
			"NOTIFIABLE_PATIENT_REQUIRED",
			_("Patient code required"),
			_("A notifiable disease report needs the patient code."),
			_("Enter the patient code (not the patient name), then save."),
		)
	disease = _disease(values.get("disease"))
	diagnosed = _moment(values.get("diagnosed_on"))
	hours = deadline_hours(disease.disease_group)
	warnings = []
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"patient_code": cstr(values["patient_code"]).strip()[:64],
			"birth_year": cint(values.get("birth_year")) or None,
			"sex": values.get("sex") or None,
			"department": values["department"],
			"disease": disease.name,
			"diagnosed_on": diagnosed,
			"deadline_hours": hours,
			"due_by": add_to_date(diagnosed, hours=hours) if hours else None,
			"outbreak_investigation": values.get("outbreak_investigation") or None,
			"notes": _text(values.get("notes"), 500) or None,
		}
	)
	doc.flags.tc_notifiable = True
	doc.insert(ignore_permissions=True)  # quyền khoa đã kiểm ở trên
	doc.submit()
	if not hours:
		warnings.append(
			_("The reporting deadline of group {0} is not configured; no due date was computed.").format(
				disease.disease_group
			)
		)
		notification.emit(
			CONFIG_EVENT,
			doc=doc,
			subject=_("Reporting deadline of disease group {0} is not configured").format(
				disease.disease_group
			),
			message=_("Set the reporting hours of group {0} in IC Program Settings.").format(
				disease.disease_group
			),
			link="/app/ic-program-settings",
		)
	doc.flags.tc_warnings = warnings
	return doc


# --- controller ---------------------------------------------------------------------------------------------------


def validate_report(doc):
	if doc.is_new() and not doc.flags.tc_notifiable:
		frappe.throw(_("Notifiable disease reports are recorded on the outbreak and notification screen."))
	patient_code.apply(doc)
	if doc.docstatus == 0:
		doc.status = DRAFT
	elif doc.docstatus == 1 and doc.status in (None, "", DRAFT):
		doc.status = PENDING


def guard_after_submit(doc):
	if not doc.flags.tc_notifiable:
		frappe.throw(_("Record the report date and reference on the outbreak and notification screen."))


def on_cancel(doc):
	doc.db_set("status", CANCELLED, update_modified=False)


# --- đã khai báo, hủy ---------------------------------------------------------------------------------------------


def _submitted(name):
	if not name or not frappe.db.exists(DOCTYPE, name):
		raise frappe.DoesNotExistError(_("Notifiable disease report {0} does not exist.").format(name))
	doc = frappe.get_doc(DOCTYPE, name)
	permissions.require_department(doc.department, code="NOTIFIABLE_NOT_ALLOWED")
	if doc.docstatus != 1:
		raise _block(
			"NOTIFIABLE_CANCELLED",
			_("Report cancelled"),
			_("Notifiable disease report {0} is cancelled.").format(doc.name),
			_("Refresh the list of reports."),
		)
	return doc


def record_reported(name, reported_on=None, report_ref=None):
	"""Ghi ngày giờ đã khai báo và số khai báo trên hệ thống quốc gia; thiếu số → vẫn Chờ, cảnh báo (E3)."""
	doc = _submitted(name)
	moment = _moment(reported_on, earliest=doc.diagnosed_on)
	ref = _text(report_ref)
	doc.reported_on = moment
	doc.report_ref = ref or None
	doc.reported_by = frappe.session.user
	doc.reported_late = int(bool(doc.due_by) and moment > get_datetime(doc.due_by))
	doc.status = REPORTED if ref else PENDING
	doc.flags.tc_notifiable = True
	doc.save(ignore_permissions=True)
	doc.flags.tc_warnings = (
		[] if ref else [_("The report reference is missing; reminders continue until it is entered.")]
	)
	if ref:
		notification.resolve(EVENT, DOCTYPE, doc.name)
	return doc


def cancel_report(name, reason=None):
	"""Hủy khai báo nhập nhầm — chỉ R01/R11, bắt buộc lý do (Audit Log)."""
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(CANCEL_ROLES):
		raise frappe.PermissionError(
			_("Only infection control staff can cancel a notifiable disease report.")
		)
	text = _text(reason)
	if not text:
		raise _block(
			"NOTIFIABLE_REASON_REQUIRED",
			_("Report not cancelled"),
			_("A reason is required to cancel a notifiable disease report."),
			_("Enter why the report is cancelled."),
		)
	doc = _submitted(name)
	doc.flags.ignore_permissions = True
	doc.cancel()
	audit.log("Cancel", DOCTYPE, doc.name, reason=text)
	doc.reload()
	return doc


# --- trạng thái, danh sách ----------------------------------------------------------------------------------------


def state_of(row, now=None) -> str:
	if cint(row.get("docstatus")) == 2 or row.get("status") == CANCELLED:
		return STATE_CANCELLED
	if row.get("reported_on") and row.get("report_ref"):
		return STATE_LATE if cint(row.get("reported_late")) else STATE_REPORTED
	if row.get("reported_on"):
		return STATE_MISSING_REF
	if not row.get("due_by"):
		return STATE_NO_DEADLINE
	return (
		STATE_OVERDUE if get_datetime(now or now_datetime()) > get_datetime(row["due_by"]) else STATE_WAITING
	)


def list_reports(departments=None, include_done_days=30, limit=200):
	"""Khai báo chưa xong và khai báo xong trong ``include_done_days`` ngày, theo phạm vi khoa; chỉ mã che."""
	filters = {"docstatus": 1}
	if departments is not None:
		filters["department"] = ["in", list(departments) or [""]]
	since = add_to_date(now_datetime(), days=-include_done_days)
	rows = frappe.get_all(
		DOCTYPE,
		filters=filters,
		or_filters={"status": PENDING, "diagnosed_on": [">=", since]},
		fields=[*LIST_FIELDS, "docstatus"],
		order_by="diagnosed_on desc",
		limit_page_length=limit,
	)
	now = now_datetime()
	for row in rows:
		row["state"] = state_of(row, now)
		row["remaining_minutes"] = (
			int((get_datetime(row.due_by) - now).total_seconds() // 60)
			if row.due_by and row["state"] in (STATE_WAITING, STATE_OVERDUE)
			else None
		)
	return rows


# --- nhắc ---------------------------------------------------------------------------------------------------------


def _recipients(department):
	users = frappe.get_all("Has Role", filters={"parenttype": "User", "role": IC_ROLE}, pluck="parent")
	users += isolates._department_role_users(department)  # "trưởng khoa" = R08 của khoa (A-136)
	return [user for user in dict.fromkeys(users) if user]


def _send(doc, overdue):
	subject = (
		_("Notifiable disease report {0} is overdue").format(doc.name)
		if overdue
		else _("Notifiable disease report {0} is due soon").format(doc.name)
	)
	message = _("{0} — {1}, patient {2}: report by {3}.").format(
		doc.disease_name or doc.disease,
		doc.department_name or doc.department,
		doc.patient_code_masked,
		frappe.utils.format_datetime(doc.due_by, "dd/MM/yyyy HH:mm"),
	)
	notification.emit(
		EVENT,
		doc=doc,
		subject=subject,
		message=message,
		users=_recipients(doc.department),
		link=f"{DESK_LINK}?report={doc.name}",
	)


def remind(now=None):
	"""Job 15 phút: nhắc nửa hạn, quá hạn, rồi mỗi ngày đến khi đủ ``reported_on`` + ``report_ref``; trả số lần nhắc."""
	now = get_datetime(now or now_datetime())
	today = getdate(now)
	count = 0
	for name in frappe.get_all(
		DOCTYPE, filters={"docstatus": 1, "status": PENDING, "due_by": ["is", "set"]}, pluck="name"
	):
		doc = frappe.get_doc(DOCTYPE, name)
		due = get_datetime(doc.due_by)
		half = get_datetime(doc.diagnosed_on) + (due - get_datetime(doc.diagnosed_on)) / 2
		stage = cint(doc.remind_stage)
		last = getdate(doc.last_reminded_on) if doc.last_reminded_on else None
		if now >= due:
			if stage >= STAGE_OVERDUE and last and last >= today:
				continue
			_send(doc, overdue=True)
			stage = STAGE_OVERDUE
		elif now >= half and stage < STAGE_HALF:
			_send(doc, overdue=False)
			stage = STAGE_HALF
		else:
			continue
		frappe.db.set_value(
			DOCTYPE, name, {"remind_stage": stage, "last_reminded_on": today}, update_modified=False
		)
		count += 1
	return count


def badge_count():
	return frappe.db.count(DOCTYPE, {"docstatus": 1, "status": PENDING, "due_by": ["<", now_datetime()]})
