"""Hồ sơ phơi nhiễm nghề nghiệp (FEAT-071; FR-M16-01..06; BRU-OCC-001..003; UC-55; A-137).

- Báo ban đầu (PDA, Cổng khoa, Desk) hoặc tự tạo từ sự cố vật sắc nhọn M10 qua hook `tracecore_exposure_incident`
  (một sự cố = một hồ sơ, BRU-OCC-002); thông báo ngay R01, R11.
- Thời gian phơi nhiễm → báo cáo → bắt đầu dự phòng, gắn cờ theo ngưỡng giờ cấu hình (không code cứng).
- R11 ghi sơ cứu và chỉ định dự phòng → chép các bước của mẫu theo dõi Approved; chỉ ghi "đã thực hiện", không có ô
  kết quả xét nghiệm hay chẩn đoán (BRU-OCC-001).
- Chỉ R01, R11 đọc hồ sơ (DocPerm + `has_permission`); nhân viên xem hồ sơ của mình qua RPC (BRU-OCC-003).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, flt, get_datetime, getdate, now_datetime, time_diff_in_seconds
from frappe.utils.password import remove_encrypted_password

from tracecore.core import notification
from tracecore.core.errors import Block, BlockedError
from tracecore.occupational_safety import config, patient_code

DOCTYPE = "Occupational Exposure"
SETTINGS = "IC Program Settings"
SCREEN_SLUG = "phoi-nhiem"
MANAGER_ROLES = ("TC R01", "TC R11", "System Manager")
CHANNELS = ("PDA", "Department Portal", "Waste Incident", "Desk")
PROPHYLAXIS = ("Given", "Not Indicated", "Refused")
SOURCE_KNOWN = ("Yes", "No", "Unknown")
FUTURE_TOLERANCE_MIN = 5
OPEN = ("New", "Following Up")
REPORT_FIELDS = ("employee", "exposure_type", "occurred_at", "activity", "device", "source_known")
SHARPS = "Needlestick or Sharps"
LINK = "/app/tc-ksnk/phoi-nhiem"


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def is_manager(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(MANAGER_ROLES))


# --- quyền (FR-M16-05, BRU-OCC-003) ---------------------------------------------------------------------------------


def has_permission(doc, ptype=None, user=None):
	return is_manager(user)


def query_conditions(user=None):
	return "" if is_manager(user) else "1=0"


# --- controller ---------------------------------------------------------------------------------------------------


def validate(doc):
	if doc.is_new():
		doc.status = "New"
		doc.reported_at = doc.reported_at or now_datetime()
		doc.reported_by = doc.reported_by or frappe.session.user
		doc.report_channel = doc.report_channel if doc.report_channel in CHANNELS else "Desk"
		doc.occupation = doc.occupation or (
			frappe.db.get_value("Employee", doc.employee, "designation") if doc.employee else None
		)
	if not doc.employee and not cint(doc.deidentified):
		raise _blocked(
			"EXPOSURE_NO_EMPLOYEE",
			_("Exposed staff member is required"),
			_("The exposure is not linked to a staff member."),
			_("Choose the staff member who was exposed, then send again."),
		)
	if doc.department is None and doc.employee:
		doc.department = frappe.db.get_value("Employee", doc.employee, "department")
	_check_time(doc)
	for field in ("activity", "device"):
		doc.set(field, cstr(doc.get(field)).strip() or None)
	patient_code.apply(doc)
	set_timing(doc)
	if doc.status == "Following Up" and doc.followups and all(row.done_on for row in doc.followups):
		doc.status = "Completed"


def after_insert(doc):
	notification.emit(
		"EXPOSURE_REPORTED",
		doc,
		subject=_("Occupational exposure {0} reported: {1}").format(doc.name, _(doc.exposure_type)),
		link=f"{LINK}?exposure={doc.name}",
	)


def _check_time(doc):
	occurred = get_datetime(doc.occurred_at)
	if time_diff_in_seconds(occurred, now_datetime()) > FUTURE_TOLERANCE_MIN * 60:
		raise _blocked(
			"EXPOSURE_TIME_INVALID",
			_("Exposure time is in the future"),
			_("The exposure time is later than now."),
			_("Check the date and time of the exposure, then send again."),
		)


def _minutes(start, end):
	return max(0, int(time_diff_in_seconds(get_datetime(end), get_datetime(start)) // 60))


def thresholds():
	"""Ngưỡng giờ R01 cấu hình (A-137 a); trống → None (không gắn cờ)."""
	values = frappe.db.get_singles_dict(SETTINGS)
	report = values.get("exposure_report_hours")
	prophylaxis = values.get("exposure_prophylaxis_hours")
	return (
		flt(report) if report not in (None, "") and flt(report) > 0 else None,
		flt(prophylaxis) if prophylaxis not in (None, "") and flt(prophylaxis) > 0 else None,
	)


def set_timing(doc):
	"""FR-M16-03: phút phơi nhiễm → báo cáo, → bắt đầu dự phòng; cờ khi vượt ngưỡng giờ."""
	report_hours, prophylaxis_hours = thresholds()
	doc.minutes_to_report = _minutes(doc.occurred_at, doc.reported_at)
	doc.report_late = int(bool(report_hours and doc.minutes_to_report > report_hours * 60))
	if doc.prophylaxis == "Given" and doc.prophylaxis_started_at:
		doc.minutes_to_prophylaxis = _minutes(doc.occurred_at, doc.prophylaxis_started_at)
		doc.prophylaxis_late = int(
			bool(prophylaxis_hours and doc.minutes_to_prophylaxis > prophylaxis_hours * 60)
		)
	else:
		doc.minutes_to_prophylaxis = None
		doc.prophylaxis_late = 0


# --- báo ban đầu (FR-M16-01) và hook M10 (FR-M16-02) ---------------------------------------------------------------


def create_report(values, channel="Desk", reported_by=None):
	"""Tạo hồ sơ từ ≤ 3 bước báo ban đầu; `values` chỉ nhận các trường của báo cáo (không có ô kết quả)."""
	data = {field: values.get(field) for field in REPORT_FIELDS}
	if data.get("source_known") not in SOURCE_KNOWN:
		data["source_known"] = "Unknown"
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			**data,
			"source_patient_code": values.get("source_patient_code")
			if data["source_known"] == "Yes"
			else None,
			"report_channel": channel,
			"reported_by": reported_by or frappe.session.user,
			# phát lại offline: giờ báo = client_ts (ADR-003); trực tuyến: giờ server nhận
			"reported_at": values.get("reported_at"),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def from_incident(incident):
	"""Hook `tracecore_exposure_incident`: sự cố phơi nhiễm vật sắc nhọn → một hồ sơ; gọi lại không tạo trùng.

	Không chép `exposure_source` của sự cố (chữ tự do, có thể có thông tin người bệnh); R11 bổ sung nguồn trên SCR-64.
	"""
	existing = frappe.db.get_value(DOCTYPE, {"incident_capa": incident.name}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"employee": incident.employee,
			"department": incident.department,
			"exposure_type": SHARPS,
			"occurred_at": incident.occurred_at or incident.creation,
			"reported_at": incident.creation or now_datetime(),
			"report_channel": "Waste Incident",
			"reported_by": incident.reported_by or incident.owner,
			"incident_capa": incident.name,
			"source_known": "Unknown",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def procedure():
	"""Quy trình xử trí ban đầu của bệnh viện: IC Procedure Document hiệu lực nhóm Occupational Exposure (A-137 i)."""
	if not frappe.db.exists("DocType", "IC Procedure Document"):
		return None
	rows = frappe.get_all(
		"IC Procedure Document",
		filters={"measure_group": "Occupational Exposure", "status": "Effective"},
		fields=["name", "title", "file"],
		order_by="issued_on desc, modified desc",
		limit=1,
	)
	return rows[0] if rows else None


# --- xử trí và theo dõi (FR-M16-03, FR-M16-04) ---------------------------------------------------------------------


def _open_doc(name):
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status not in OPEN:
		raise _blocked(
			"EXPOSURE_STATUS_INVALID",
			_("Exposure record is closed"),
			_("Exposure record {0} is {1}.").format(name, _(doc.status)),
			_("Open an exposure record that is new or being followed up."),
		)
	return doc


def record_handling(name, first_aid_done=0, first_aid_at=None, prophylaxis=None, prophylaxis_started_at=None):
	"""R11 ghi sơ cứu và chỉ định dự phòng; lần đầu có mẫu Approved thì sinh lịch theo dõi."""
	doc = _open_doc(name)
	if prophylaxis not in PROPHYLAXIS or (prophylaxis == "Given" and not prophylaxis_started_at):
		raise _blocked(
			"EXPOSURE_HANDLING_INCOMPLETE",
			_("Prophylaxis decision is required"),
			_(
				"Choose whether prophylaxis was given, not indicated or refused; when given, enter the start time."
			),
			_("Complete the prophylaxis decision, then save again."),
		)
	doc.first_aid_done = cint(first_aid_done)
	doc.first_aid_at = (first_aid_at or doc.first_aid_at or now_datetime()) if doc.first_aid_done else None
	doc.prophylaxis = prophylaxis
	doc.prophylaxis_started_at = prophylaxis_started_at if prophylaxis == "Given" else None
	if not doc.followups:
		_schedule(doc)
	doc.save(ignore_permissions=True)
	return doc


def _schedule(doc):
	template = config.active_template(doc.exposure_type)
	if not template:
		notification.emit(
			"EXPOSURE_TEMPLATE_MISSING",
			doc,
			subject=_("No approved follow-up template for {0}").format(_(doc.exposure_type)),
			link="/app/exposure-follow-up-template",
		)
		return
	base = getdate(doc.occurred_at)
	for row in template.steps:
		doc.append(
			"followups",
			{
				"step": row.step,
				"days_after": row.days_after,
				"due_date": add_days(base, cint(row.days_after)),
			},
		)
	doc.followup_template = template.name
	doc.template_version = template.version_no
	doc.status = "Following Up"


def mark_followup_done(name, row_name, done_on):
	"""Ghi ngày đã thực hiện một mốc (không ghi kết quả); đủ mốc → Completed."""
	doc = _open_doc(name)
	row = next((r for r in doc.followups if r.name == row_name), None)
	done = getdate(done_on) if done_on else None
	if not row or not done or done > getdate() or done < getdate(doc.occurred_at):
		raise _blocked(
			"EXPOSURE_STEP_INVALID",
			_("Follow-up step cannot be recorded"),
			_("The step is not on this record, or the date is before the exposure or after today."),
			_("Choose a step of this record and a date from the exposure day to today."),
		)
	row.done_on = done
	doc.save(ignore_permissions=True)
	return doc


def cancel(name, reason):
	"""Hủy hồ sơ báo nhầm (R01/R11), bắt buộc lý do; không xóa."""
	doc = _open_doc(name)
	reason = cstr(reason).strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("A cancelled exposure record needs a reason."),
			_("Enter the reason, then cancel again."),
		)
	doc.status = "Cancelled"
	doc.cancel_reason = reason
	doc.save(ignore_permissions=True)
	return doc


# --- đọc --------------------------------------------------------------------------------------------------------


def employee_of(user=None):
	return frappe.db.get_value(
		"Employee", {"user_id": user or frappe.session.user, "status": "Active"}, "name"
	)


def my_records(user=None):
	"""A4: nhân viên xem hồ sơ của mình — không có mã BN nguồn."""
	employee = employee_of(user)
	if not employee:
		return []
	rows = frappe.get_all(
		DOCTYPE,
		filters={"employee": employee, "status": ["!=", "Cancelled"]},
		fields=["name", "exposure_type", "occurred_at", "status", "prophylaxis"],
		order_by="occurred_at desc",
		limit=50,
	)
	for row in rows:
		row.followups = frappe.get_all(
			"Exposure Follow-up",
			filters={"parent": row.name, "parenttype": DOCTYPE},
			fields=["step", "due_date", "done_on"],
			order_by="idx",
		)
	return rows


def badges(user):
	"""Hook `tracecore_ksnk_badges`: số hồ sơ mới chờ xử trí cho R01/R11."""
	if not is_manager(user):
		return {}
	return {SCREEN_SLUG: frappe.db.count(DOCTYPE, {"status": "New"})}


def deidentify(doc):
	"""NFR-PRIV-02: bỏ định danh nhân viên và mã BN nguồn, giữ số liệu tổng hợp."""
	doc.employee = doc.employee_name = doc.reported_by = None
	doc.source_patient_code = doc.source_patient_code_masked = doc.source_patient_code_hash = None
	doc.deidentified = 1
	remove_encrypted_password(DOCTYPE, doc.name, "source_patient_code")
	doc.flags.ignore_links = True
	doc.save(ignore_permissions=True)
