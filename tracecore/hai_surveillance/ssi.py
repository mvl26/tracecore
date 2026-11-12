"""Giám sát nhiễm khuẩn vết mổ theo QĐ 1526/QĐ-BYT (FEAT-064; FR-M13-07, 07.1, 07.2, 08, 08.1, 09, 09.1, 09.2;
BRU-HAI-003, BRU-HAI-004, BRU-HAI-005, BRU-RPT-003; UC-49; A-147 Q2, Q3, a-h, l).

- `Surgical Procedure Group`: T của NNIS, cửa sổ 30/90 ngày (nhóm có cấy ghép buộc 90), lịch theo dõi sau ra viện
  (ngày thứ N tính từ ngày mổ). Danh mục cấu hình do R01 duyệt; không mã hóa tiêu chí trong code.
- `Surgical Surveillance`: NNIS = (ASA ≥ 3) + (vết mổ Nhiễm/Bẩn) + (thời gian mổ > T) với T chụp lại trên ca; cửa sổ =
  90 ngày khi nhóm hoặc ca có cấy ghép, ngược lại theo nhóm; ra viện → sinh lịch theo dõi (lần sau ra viện, trước cửa
  sổ, luôn một lần cuối đúng ngày kết thúc cửa sổ).
- Kết cục: ca NKBV Xác định gắn → SSI; hết cửa sổ mà lần cuối chưa làm / không liên lạc được → Mất theo dõi (FR-M13-08.1);
  mọi lần đã làm âm tính → Không NKVM; ca không có lịch (ra viện sau cửa sổ, A2) do R11 đóng tay.
- Kháng sinh dự phòng: ngưỡng phút ở `IC Program Settings.prophylaxis_max_minutes`; mỗi ca chụp ngưỡng và kết quả; đổi
  ngưỡng chỉ tính lại ca thuộc kỳ chưa khóa (FR-M13-09.2).
- Kỳ đã khóa chặn sửa trường đăng ký; ra viện, theo dõi, kết cục vẫn ghi được (A-147 g).
"""

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_days, cint, formatdate, get_datetime, getdate, now_datetime, today
from frappe.utils.password import get_decrypted_password

from tracecore.core import notification, patient_code
from tracecore.core.errors import Block, BlockedError
from tracecore.hai_surveillance import periods

DOCTYPE = "Surgical Surveillance"
GROUP = "Surgical Procedure Group"
GROUP_FOLLOWUP = "Surgical Procedure Group Follow-up"
FOLLOWUP = "SSI Follow-up"
CASE = "HAI Case"
SETTINGS = "IC Program Settings"
THRESHOLD_FIELD = "prophylaxis_max_minutes"
UNDER, NO_SSI, SSI, LOST = "Under Surveillance", "No SSI", "SSI", "Lost to Follow-up"
NOT_GIVEN, ON_TIME, LATE, TOO_EARLY, NOT_ASSESSED = (
	"Not given",
	"On time",
	"Late",
	"Too early",
	"Not assessed",
)
NEGATIVE, SUSPECTED, UNREACHABLE = "Negative", "SSI suspected", "Unreachable"
RESULTS = (NEGATIVE, SUSPECTED, UNREACHABLE)
DIRTY_WOUNDS = ("Contaminated", "Dirty")
WOUNDS = ("Clean", "Clean-Contaminated", *DIRTY_WOUNDS)
IMPORT = "Import"
SHORT_WINDOW, IMPLANT_WINDOW = 30, 90
DEFAULT_METHOD = "Phone"
WORK_ROLES = ("TC R01", "TC R11")
T_MISSING_EVENT = "SSI_GROUP_T_MISSING"
DUE_EVENT = "SSI_FOLLOWUP_DUE"
# trường đăng ký: kỳ đã khóa thì không sửa (A-147 g); ra viện, theo dõi, kết cục vẫn ghi được
REGISTRATION_FIELDS = (
	"department",
	"procedure_group",
	"patient_code_hash",
	"birth_year",
	"sex",
	"surgery_date",
	"asa_score",
	"wound_class",
	"duration_min",
	"has_implant",
	"prophylaxis_given",
	"prophylaxis_agent",
	"prophylaxis_minutes_before_incision",
)
INT_FIELDS = frozenset(
	{
		"asa_score",
		"duration_min",
		"birth_year",
		"has_implant",
		"prophylaxis_given",
		"prophylaxis_minutes_before_incision",
	}
)
LIST_FIELDS = (
	"name",
	"patient_code_masked",
	"birth_year",
	"sex",
	"department",
	"department_name",
	"procedure_group",
	"group_name",
	"surgery_date",
	"asa_score",
	"wound_class",
	"duration_min",
	"has_implant",
	"nnis_index",
	"nnis_note",
	"window_days",
	"window_end",
	"prophylaxis_given",
	"prophylaxis_agent",
	"prophylaxis_minutes_before_incision",
	"prophylaxis_timing",
	"prophylaxis_max_applied",
	"discharge_date",
	"outcome",
	"hai_case",
	"reporting_period",
	"data_complete",
	"source",
)


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


def _invalid(reason, field=None):
	return blocked(
		"SSI_VALUE_INVALID",
		_("Value not valid"),
		reason,
		_("Correct the value and save again."),
		items=[field] if field else [],
	)


def _bad_date(reason, field):
	return blocked("SSI_DATE_INVALID", _("Date not valid"), reason, _("Correct the dates."), items=[field])


def _empty(value):
	return value is None or (isinstance(value, str) and not value.strip())


def minutes_of(value):
	"""Phút trước rạch da (Data): None khi trống; số nguyên (âm = sau rạch da); chữ khác → ValueError."""
	if _empty(value):
		return None
	text = str(value).strip()
	number = float(text.replace(",", "."))
	if not number.is_integer():
		raise ValueError(text)
	return int(number)


# --- nhóm phẫu thuật ------------------------------------------------------------------------------------------------


def validate_group(doc):
	"""Nhóm có cấy ghép theo dõi 90 ngày (FR-M13-07.2); lần theo dõi nằm trong cửa sổ, không trùng ngày."""
	doc.group_code = (doc.group_code or "").strip().upper()
	if cint(doc.has_implant) and cint(doc.followup_days) != IMPLANT_WINDOW:
		frappe.throw(_("A group with an implant is followed for {0} days.").format(IMPLANT_WINDOW))
	if not _empty(doc.t_time_minutes) and cint(doc.t_time_minutes) < 0:
		frappe.throw(_("T must be more than 0 minutes, or empty when not configured."))
	window = cint(doc.followup_days)
	seen = set()
	for row in doc.followups or []:
		day = cint(row.day_offset)
		if not 1 <= day <= window:
			frappe.throw(_("Row {0}: the follow-up day must be from 1 to {1}.").format(row.idx, window))
		if day in seen:
			frappe.throw(_("Row {0}: day {1} is listed twice.").format(row.idx, day))
		seen.add(day)
	doc.followups.sort(key=lambda row: cint(row.day_offset))
	for index, row in enumerate(doc.followups, start=1):
		row.idx = index


def _group(name):
	row = frappe.db.get_value(
		GROUP,
		name,
		["name", "group_name", "t_time_minutes", "has_implant", "followup_days", "is_monitored"],
		as_dict=True,
	)
	if not row:
		raise _invalid(_("Procedure group {0} does not exist.").format(name or "-"), "procedure_group")
	return row


def _group_schedule(name):
	return frappe.get_all(
		GROUP_FOLLOWUP,
		filters={"parent": name, "parenttype": GROUP},
		fields=["day_offset", "method"],
		order_by="day_offset asc",
	)


def monitored_groups():
	return frappe.get_all(
		GROUP,
		filters={"is_monitored": 1},
		fields=["name", "group_name", "t_time_minutes", "has_implant", "followup_days"],
		order_by="group_name asc",
	)


# --- tính toán ------------------------------------------------------------------------------------------------------


def nnis(asa, wound, duration, t_time):
	"""(chỉ số 0 đến 3 | None, ghi chú) theo BRU-HAI-003; thiếu T của nhóm hoặc thiếu dữ liệu → None."""
	if not cint(t_time):
		return None, _("The procedure group has no T: the NNIS index is not calculated.")
	if not cint(asa) or not wound or not cint(duration):  # Int của Frappe lưu trống thành 0
		return None, _("ASA, wound class or duration missing: the NNIS index is not calculated yet.")
	parts = (int(cint(asa) >= 3), int(wound in DIRTY_WOUNDS), int(cint(duration) > cint(t_time)))
	return sum(parts), _(
		"ASA ≥ 3 ({0}) + Contaminated or Dirty wound ({1}) + duration > T {2} min ({3})"
	).format(parts[0], parts[1], cint(t_time), parts[2])


def window_days(group, has_implant):
	"""BRU-HAI-004: 90 ngày khi nhóm hoặc ca có cấy ghép, ngược lại theo nhóm (30)."""
	if cint(group.has_implant) or cint(has_implant):
		return IMPLANT_WINDOW
	return cint(group.followup_days) or SHORT_WINDOW


def prophylaxis_timing(given, minutes, limit):
	"""FR-M13-09: Đúng = 0 ≤ phút trước rạch da ≤ ngưỡng; âm = sau rạch da (Muộn); trên ngưỡng = Quá sớm; ngưỡng trống/0 = không đánh giá."""
	if not cint(given):
		return NOT_GIVEN
	try:
		minutes = minutes_of(minutes)
	except ValueError:
		minutes = None
	if minutes is None or _empty(limit) or cint(limit) <= 0:
		return NOT_ASSESSED
	if minutes < 0:
		return LATE
	if minutes > cint(limit):
		return TOO_EARLY
	return ON_TIME


def threshold():
	"""Ngưỡng phút đang cấu hình; trống hoặc 0 → None (không đánh giá, OQ-V12-09).

	Ô Int trống bị Frappe lưu thành 0 mỗi lần lưu IC Program Settings, nên 0 cũng là "chưa cấu hình".
	"""
	raw = frappe.db.get_value(
		"Singles", {"doctype": SETTINGS, "field": THRESHOLD_FIELD}, "value", order_by=None
	)
	return None if _empty(raw) or cint(raw) <= 0 else cint(raw)


def schedule_rows(surgery_date, window, discharge_date, plan):
	"""[(hạn, cách, lần cuối)] theo A-147 Q2: lần sau ra viện và trước cửa sổ, cộng lần cuối đúng ngày kết thúc."""
	if not discharge_date:
		return []
	surgery, discharge = getdate(surgery_date), getdate(discharge_date)
	end = getdate(add_days(surgery, window))
	if discharge >= end:
		return []
	rows = []
	final_method = DEFAULT_METHOD
	for line in plan:
		day = cint(line.day_offset)
		due = getdate(add_days(surgery, day))
		if day == window:
			final_method = line.method or DEFAULT_METHOD
		elif due > discharge and day < window:
			rows.append((due, line.method or DEFAULT_METHOD, 0))
	rows.append((end, final_method, 1))
	return rows


# --- kiểm khi lưu ---------------------------------------------------------------------------------------------------


def _before(doc):
	if doc.is_new():
		return None
	return frappe.db.get_value(DOCTYPE, doc.name, [*REGISTRATION_FIELDS, "outcome"], as_dict=True)


def _norm(field, value):
	if field == "surgery_date":
		return getdate(value) if value else None
	if field == "prophylaxis_minutes_before_incision":
		try:
			return minutes_of(value)
		except ValueError:
			return str(value)
	if field in INT_FIELDS:
		return cint(value) or None  # Int của Frappe: trống = 0
	return value or None


def _registration_changed(doc, before):
	if before is None:
		return True
	return any(
		_norm(field, before.get(field)) != _norm(field, doc.get(field)) for field in REGISTRATION_FIELDS
	)


def _check_values(doc):
	manual = (doc.source or "Manual") != IMPORT
	if _empty(doc.asa_score) and manual:
		raise _invalid(_("Enter the ASA score from 1 to 5."), "asa_score")
	if not _empty(doc.asa_score) and not 1 <= cint(doc.asa_score) <= 5 and (manual or cint(doc.asa_score)):
		raise _invalid(_("The ASA score {0} is not from 1 to 5.").format(doc.asa_score), "asa_score")
	if not doc.wound_class and manual:
		raise _invalid(_("Choose the wound class."), "wound_class")
	if doc.wound_class and doc.wound_class not in WOUNDS:
		raise _invalid(_("Wound class {0} is not valid.").format(doc.wound_class), "wound_class")
	if _empty(doc.duration_min) and manual:
		raise _invalid(_("Enter the duration of the operation in minutes."), "duration_min")
	if (
		not _empty(doc.duration_min)
		and cint(doc.duration_min) <= 0
		and (manual or cint(doc.duration_min) < 0)
	):
		raise _invalid(_("The duration must be more than 0 minutes."), "duration_min")
	try:
		minutes = minutes_of(doc.prophylaxis_minutes_before_incision)
	except ValueError:
		raise _invalid(
			_("Minutes before incision must be a whole number."), "prophylaxis_minutes_before_incision"
		) from None
	doc.prophylaxis_minutes_before_incision = None if minutes is None else str(minutes)
	if cint(doc.birth_year) and not 1900 <= cint(doc.birth_year) <= now_datetime().year:
		raise _invalid(_("Birth year {0} is not valid.").format(doc.birth_year), "birth_year")


def _check_dates(doc):
	surgery = getdate(doc.surgery_date)
	if surgery > getdate(today()):
		raise _bad_date(
			_("The surgery date {0} is later than today.").format(formatdate(surgery)), "surgery_date"
		)
	if doc.discharge_date and getdate(doc.discharge_date) < surgery:
		raise _bad_date(
			_("The discharge date {0} is before the surgery date {1}.").format(
				formatdate(doc.discharge_date), formatdate(surgery)
			),
			"discharge_date",
		)


def _warn_t_missing(group):
	"""UC-49 E4: nhóm chưa có T → báo R01 một lần mỗi nhóm."""
	if frappe.db.exists("Notification Delivery", {"event_code": T_MISSING_EVENT, "ref_name": group.name}):
		return
	label = group.group_name or group.name
	notification.emit(
		T_MISSING_EVENT,
		frappe._dict(doctype=GROUP, name=group.name),
		subject=_("Procedure group {0} has no NNIS cut-off T").format(label),
		message=_("Enter T (minutes) for procedure group {0} so the NNIS index can be calculated.").format(
			label
		),
	)


def _compute(doc, group):
	index, note = nnis(doc.asa_score, doc.wound_class, doc.duration_min, group.t_time_minutes)
	doc.nnis_index, doc.nnis_note = ("" if index is None else str(index)), note
	doc.t_time_applied = cint(group.t_time_minutes) or None
	doc.data_complete = int(bool(cint(doc.asa_score) and doc.wound_class and cint(doc.duration_min)))
	if not cint(group.t_time_minutes):
		_warn_t_missing(group)
	limit = threshold()
	doc.prophylaxis_timing = prophylaxis_timing(
		doc.prophylaxis_given, doc.prophylaxis_minutes_before_incision, limit
	)
	doc.prophylaxis_max_applied = limit


def _schedule(doc):
	"""Giữ lần đã làm; sinh lại lần chưa làm theo ngày ra viện và cửa sổ hiện tại."""
	plan = _group_schedule(doc.procedure_group)
	wanted = schedule_rows(doc.surgery_date, cint(doc.window_days), doc.discharge_date, plan)
	plan_by_due = {due: (method, final) for due, method, final in wanted}
	kept = []
	for row in doc.followups or []:
		due = getdate(row.due_date)
		if row.done_on or row.result:
			kept.append(row)
		elif due in plan_by_due:  # lần chưa làm còn đúng lịch: giữ nguyên dòng (tên dòng không đổi)
			row.method, row.is_final = plan_by_due[due]
			kept.append(row)
	have = {getdate(row.due_date) for row in kept}
	for row in kept:
		if getdate(row.due_date) in plan_by_due:
			row.is_final = plan_by_due[getdate(row.due_date)][1]
	doc.set("followups", kept)
	for due, method, final in wanted:
		if due not in have:
			doc.append("followups", {"due_date": due, "method": method, "is_final": final})
	doc.followups.sort(key=lambda row: getdate(row.due_date))
	for index, row in enumerate(doc.followups, start=1):
		row.idx = index


def validate(doc):
	"""Gọi từ ``SurgicalSurveillance.validate``."""
	patient_code.apply(doc)
	if not doc.patient_code and not cint(doc.deidentified):
		frappe.throw(_("Enter the patient code; the patient name is never recorded."))
	before = _before(doc)
	changed = _registration_changed(doc, before)
	if changed and not doc.flags.tc_system:
		periods.ensure_open(doc.surgery_date, DOCTYPE, None if doc.is_new() else doc.name)
		if before and before.surgery_date:
			periods.ensure_open(before.surgery_date, DOCTYPE, doc.name)
	group = _group(doc.procedure_group)
	if not cint(group.is_monitored) and (before is None or before.procedure_group != doc.procedure_group):
		raise blocked(
			"SSI_GROUP_NOT_MONITORED",
			_("Group not monitored"),
			_("Procedure group {0} is not under surveillance.").format(group.group_name or group.name),
			_("Choose a monitored group, or ask the head of infection control to turn it on."),
			items=["procedure_group"],
		)
	_check_values(doc)
	_check_dates(doc)
	doc.reporting_period = periods.month_of(doc.surgery_date)
	doc.window_days = window_days(group, doc.has_implant)
	doc.window_end = add_days(getdate(doc.surgery_date), doc.window_days)
	if changed or not periods.is_locked(doc.reporting_period):
		_compute(doc, group)
	_schedule(doc)
	doc.outcome = outcome_of(doc, keep=(before or {}).get("outcome"))


def on_trash(doc):
	frappe.throw(_("A surgical surveillance record is never deleted."))


# --- kết cục --------------------------------------------------------------------------------------------------------


def _case_confirmed(name):
	if not name:
		return False
	row = frappe.db.get_value(CASE, name, ["docstatus", "status"], as_dict=True)
	return bool(row and row.docstatus == 1 and row.status == "Confirmed")


def outcome_of(doc, day=None, keep=None):
	"""Kết cục theo A-147 e; ``keep`` = kết cục R11 đã đóng tay cho ca không có lịch theo dõi (A2)."""
	if _case_confirmed(doc.hai_case):
		return SSI
	if not doc.window_end or getdate(day or today()) <= getdate(doc.window_end):
		return UNDER
	rows = list(doc.followups or [])
	if not rows:
		return keep if keep in (NO_SSI, LOST) else UNDER
	final = next((row for row in rows if cint(row.is_final)), rows[-1])
	if not final.done_on or final.result == UNREACHABLE:
		return LOST
	if any(row.result == SUSPECTED for row in rows if row.done_on):
		return UNDER  # còn chờ R11 tạo/xác định ca NKBV
	return NO_SSI


def refresh(name):
	doc = frappe.get_doc(DOCTYPE, name)
	value = outcome_of(doc, keep=doc.outcome)
	if value != doc.outcome:
		frappe.db.set_value(DOCTYPE, name, "outcome", value)
	return value


def run_daily(day=None):
	"""Scheduler hằng ngày: ca hết cửa sổ còn Đang theo dõi → cập nhật kết cục (FR-M13-08, 08.1)."""
	for name in frappe.get_all(
		DOCTYPE,
		filters={"outcome": UNDER, "window_end": ["<", getdate(day or today())]},
		pluck="name",
	):
		refresh(name)


# --- thao tác -------------------------------------------------------------------------------------------------------


def _writable(name):
	if not frappe.has_permission(DOCTYPE, "write", name):
		raise frappe.PermissionError(
			_("You are not allowed to change surgical surveillance {0}.").format(name)
		)
	return frappe.get_doc(DOCTYPE, name)


def record_followup(name, row, done_on, result, note=None):
	"""R11 ghi kết quả một lần theo dõi (điện thoại / tái khám / hồ sơ)."""
	doc = _writable(name)
	line = next((item for item in doc.followups if item.name == row), None)
	if not line:
		frappe.throw(_("Follow-up {0} is not part of {1}.").format(row, name))
	if result not in RESULTS:
		raise _invalid(_("Choose the result of the follow-up."), "result")
	if not done_on:
		raise _bad_date(_("Enter the day of the follow-up."), "done_on")
	day = getdate(done_on)
	if day > getdate(today()):
		raise _bad_date(_("The follow-up day {0} is later than today.").format(formatdate(day)), "done_on")
	if day < getdate(doc.surgery_date):
		raise _bad_date(_("The follow-up day {0} is before the surgery.").format(formatdate(day)), "done_on")
	line.update(
		{
			"done_on": day,
			"result": result,
			"note": (note or "").strip() or None,
			"done_by": frappe.session.user,
		}
	)
	doc.flags.ignore_permissions = True
	doc.save()
	return doc


def close(name, outcome, reason=None):
	"""A2: ca ra viện sau cửa sổ (không có lịch theo dõi) — R11 đóng Không NKVM hoặc Mất theo dõi khi hết cửa sổ."""
	doc = _writable(name)
	if outcome not in (NO_SSI, LOST):
		raise _invalid(
			_("Close the surgery as No SSI or Lost to Follow-up; an SSI needs a confirmed case."), "outcome"
		)
	if getdate(today()) <= getdate(doc.window_end):
		raise blocked(
			"SSI_WINDOW_OPEN",
			_("Surveillance window still open"),
			_("The surveillance window of {0} ends on {1}.").format(name, formatdate(doc.window_end)),
			_("Record the follow-ups until the window ends."),
		)
	if doc.followups:
		raise _invalid(_("This surgery has a follow-up schedule; record the follow-ups instead."), "outcome")
	frappe.db.set_value(DOCTYPE, name, "outcome", outcome)
	if reason:
		doc.add_comment("Comment", text=reason)
	doc.reload()
	return doc


def create_case(name, def_code, onset_date):
	"""Tạo ca NKBV Nghi ngờ từ ca phẫu thuật (UC-49 bước 5): mã BN, năm sinh, giới, khoa chép sang ở server."""
	doc = _writable(name)
	if doc.hai_case and frappe.db.get_value(CASE, doc.hai_case, "docstatus") == 0:
		return frappe.get_doc(CASE, doc.hai_case)
	code = get_decrypted_password(DOCTYPE, name, "patient_code", raise_exception=False)
	case = frappe.get_doc(
		{
			"doctype": CASE,
			"department": doc.department,
			"patient_code": code,
			"birth_year": doc.birth_year,
			"sex": doc.sex,
			"admission_at": get_datetime(getdate(doc.surgery_date)),
			"onset_date": getdate(onset_date),
			"def_code": def_code,
			"surgical_surveillance": name,
		}
	)
	case.flags.ignore_permissions = True
	case.insert()
	frappe.db.set_value(DOCTYPE, name, "hai_case", case.name)
	return case


def on_case_change(case, method=None):
	"""doc_events HAI Case on_submit / on_cancel: ca gắn ca phẫu thuật → cập nhật liên kết và kết cục."""
	name = case.get("surgical_surveillance")
	if not name or not frappe.db.exists(DOCTYPE, name):
		return
	if case.docstatus == 1 and case.status == "Confirmed":
		frappe.db.set_value(DOCTYPE, name, "hai_case", case.name)
	refresh(name)


def check_case_link(case):
	"""Gọi từ ``cases.validate``: ca phẫu thuật gắn vào ca NKBV phải cùng người bệnh (hash)."""
	if not case.surgical_surveillance:
		return
	row = frappe.db.get_value(DOCTYPE, case.surgical_surveillance, ["patient_code_hash"], as_dict=True)
	if not row or (case.patient_code_hash and row.patient_code_hash != case.patient_code_hash):
		raise blocked(
			"HAI_CASE_SURGERY_INVALID",
			_("Surgery not valid"),
			_("Surgical surveillance {0} belongs to another patient.").format(case.surgical_surveillance),
			_("Choose a surgery of this patient."),
			items=["surgical_surveillance"],
		)


# --- kháng sinh dự phòng -------------------------------------------------------------------------------------------


def recalculate_prophylaxis():
	"""Tính lại kết quả KSDP theo ngưỡng hiện tại cho ca thuộc kỳ chưa khóa (FR-M13-09.2); trả số ca đổi."""
	limit = threshold()
	applied = limit or 0  # cột Int NOT NULL: 0 = không có ngưỡng
	locked = frappe.get_all("IC Reporting Period", filters={"locked": 1}, pluck="month")
	changed = 0
	for row in frappe.get_all(
		DOCTYPE,
		filters={"reporting_period": ["not in", locked or [""]]},
		fields=[
			"name",
			"prophylaxis_given",
			"prophylaxis_minutes_before_incision",
			"prophylaxis_timing",
			"prophylaxis_max_applied",
		],
	):
		timing = prophylaxis_timing(row.prophylaxis_given, row.prophylaxis_minutes_before_incision, limit)
		if timing != row.prophylaxis_timing or cint(row.prophylaxis_max_applied) != applied:
			frappe.db.set_value(
				DOCTYPE,
				row.name,
				{"prophylaxis_timing": timing, "prophylaxis_max_applied": applied},
				update_modified=False,
			)
			changed += 1
	return changed


def on_settings_update(doc, method=None):
	"""doc_events IC Program Settings on_update: ngưỡng phút đổi → tính lại kỳ chưa khóa."""
	before = doc.get_doc_before_save()
	if before is None or before.get(THRESHOLD_FIELD) != doc.get(THRESHOLD_FIELD):
		recalculate_prophylaxis()


# --- lịch theo dõi đến hạn, nhắc ------------------------------------------------------------------------------------


def due_followups(day=None, limit=200):
	"""Lần theo dõi chưa làm có hạn ≤ ``day`` của ca Đang theo dõi (mã BN che)."""
	rows = frappe.db.sql(
		"""
		select s.name, s.patient_code_masked, s.group_name, s.procedure_group, s.department_name,
			s.surgery_date, s.window_end, f.name as `row`, f.due_date, f.method, f.is_final
		from `tabSSI Follow-up` f
		join `tabSurgical Surveillance` s on s.name = f.parent and f.parenttype = 'Surgical Surveillance'
		where f.done_on is null and f.due_date <= %(day)s and s.outcome = %(under)s
		order by f.due_date asc, s.name asc
		limit %(limit)s
		""",
		{"day": getdate(day or today()), "under": UNDER, "limit": cint(limit)},
		as_dict=True,
	)
	return [dict(row) for row in rows]


def remind(now=None):
	"""Cron 15 phút (ADR-014): sau giờ nhắc mẫu số, một thông báo mỗi ngày liệt kê lần theo dõi đến hạn cho R11."""
	from tracecore.hai_surveillance import reminders

	now = get_datetime(now) if now else now_datetime()
	day = getdate(now)
	if now < datetime.combine(day, reminders._time("census_reminder_time")):
		return
	rows = due_followups(day)
	if not rows:
		return
	header = _("Surgical site infection follow-ups due on {0}:").format(formatdate(day))
	if frappe.db.exists(
		"Notification Delivery", {"event_code": DUE_EVENT, "message": ["like", f"{header}%"]}
	):
		return
	lines = [
		f"{row['name']} · {row['patient_code_masked']} · {row['group_name'] or ''} · {formatdate(row['due_date'])}"
		for row in rows
	]
	notification.emit(
		DUE_EVENT,
		None,
		subject=_("{0} surgical site infection follow-ups due").format(len(rows)),
		message="\n".join([header, *lines]),
		link="/app/tc-ksnk/nkvm",
	)


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: số lần theo dõi đến hạn/quá hạn (SCR-57), chỉ R01/R11."""
	if not set(frappe.get_roles(user)) & set(WORK_ROLES):
		return {}
	return {"nkvm": len(due_followups())}
