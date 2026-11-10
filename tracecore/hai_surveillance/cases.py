"""Ca NKBV `HAI Case` (FEAT-063; FR-M13-05, 05.1, 05.2, 06, 06.1, 11, 15, 15.1; BRU-HAI-001, BRU-HAI-005; UC-48;
A-144 Q2, b, h).

- Nháp = Nghi ngờ (R08/R12 khoa mình, R11, R01 tạo). ``decide`` = R11/R01 đặt Xác định hoặc Loại trừ rồi ghi sổ;
  Loại trừ bắt buộc lý do; ghi sổ trực tiếp không qua ``decide`` bị chặn.
- Gắn bản chụp phiên bản định nghĩa có hiệu lực tại ngày khởi phát (BRU-HAI-001) và kiểm ngưỡng thời gian của chính
  phiên bản đó (FR-M13-06.1). Không đạt → ``time_check = Not met``; Xác định cần ``exception_reason`` (Audit Log).
- Mã người bệnh: Password + hash + bản che (`core.patient_code`); danh sách chỉ mã che; không trường họ tên.
- Kỳ đã khóa (`periods`) chặn mọi ghi vào ca có ngày khởi phát trong kỳ, trừ nhãn đa kháng do hệ thống cộng.
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, formatdate, get_datetime, getdate, now_datetime, today

from tracecore.core import audit, patient_code
from tracecore.core.errors import Block, BlockedError
from tracecore.hai_surveillance import definitions, periods, permissions, ssi

DOCTYPE = "HAI Case"
EPISODE = "Device Episode"
ISOLATE = "Microbiology Isolate"
SUSPECTED, CONFIRMED, EXCLUDED = "Suspected", "Confirmed", "Excluded"
MET, NOT_MET, NOT_APPLICABLE = "Met", "Not met", "Not applicable"
DECIDE_ROLES = ("TC R01", "TC R11")
AFTER_SUBMIT = frozenset(
	{"outcome", "isolates", "mdro_flags", "deidentified", "modified", "modified_by", "_comments", "_assign"}
)
LIST_FIELDS = (
	"name",
	"department",
	"department_name",
	"patient_code_masked",
	"birth_year",
	"sex",
	"admission_at",
	"onset_date",
	"def_code",
	"case_definition",
	"infection_site",
	"device_type",
	"status",
	"docstatus",
	"reporting_period",
	"mdro_flags",
	"outcome",
)
DETAIL_FIELDS = (
	*LIST_FIELDS,
	"device_episode",
	"time_check",
	"time_check_note",
	"exception_reason",
	"exclusion_reason",
	"confirmed_by",
	"confirmed_on",
	"deidentified",
)


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


def _flags(*values):
	labels = []
	for value in values:
		labels += [part.strip() for part in str(value or "").split(",") if part.strip()]
	return ", ".join(dict.fromkeys(labels)) or None


# --- kiểm ---------------------------------------------------------------------------------------------------------


def _attach_definition(doc):
	doc.def_code = (doc.def_code or "").strip().upper()
	name = definitions.effective_for(doc.def_code, doc.onset_date)
	if not name:
		raise blocked(
			"HAI_CASE_DEFINITION_MISSING",
			_("No approved case definition"),
			_("Definition {0} has no approved version in force on {1}.").format(
				doc.def_code or "-", formatdate(doc.onset_date)
			),
			_("Choose another definition, or ask the head of infection control to approve one."),
			items=["def_code"],
		)
	doc.case_definition = name
	row = frappe.db.get_value(definitions.DOCTYPE, name, ["infection_site", "device_type"], as_dict=True)
	doc.infection_site, doc.device_type = row.infection_site, row.device_type


def _check_dates(doc):
	onset, admitted = getdate(doc.onset_date), get_datetime(doc.admission_at)
	if onset > getdate(today()):
		reason = _("The onset date {0} is later than today.").format(formatdate(onset))
	elif admitted.date() > onset:
		reason = _("The onset date {0} is before the admission date {1}.").format(
			formatdate(onset), formatdate(admitted.date())
		)
	else:
		return
	raise blocked(
		"HAI_CASE_DATE_INVALID", _("Date not valid"), reason, _("Correct the dates."), items=["onset_date"]
	)


def _episode(doc):
	if not doc.device_episode:
		return None
	row = frappe.db.get_value(
		EPISODE, doc.device_episode, ["patient_code_hash", "inserted_on", "device_type"], as_dict=True
	)
	if not row or (doc.patient_code_hash and row.patient_code_hash != doc.patient_code_hash):
		raise blocked(
			"HAI_CASE_EPISODE_INVALID",
			_("Device episode not valid"),
			_("Device episode {0} belongs to another patient.").format(doc.device_episode),
			_("Choose a device episode of this patient."),
			items=["device_episode"],
		)
	return row


def time_check(doc):
	"""(kết quả, ghi chú) theo ngưỡng của phiên bản định nghĩa đã gắn (FR-M13-06, 06.1)."""
	ref = frappe.db.get_value(
		definitions.DOCTYPE,
		doc.case_definition,
		["name", "device_type", *definitions.THRESHOLDS],
		as_dict=True,
	)
	need_hours = cint(ref.min_hours_after_admission)
	need_days = cint(ref.min_device_days_before_onset)
	onset_start = get_datetime(getdate(doc.onset_date))
	hours = int((onset_start - get_datetime(doc.admission_at)).total_seconds() // 3600)
	notes, met = [], True
	if need_hours:
		ok = hours >= need_hours
		met = met and ok
		notes.append(
			_("Onset {0} hours after admission (required at least {1} hours).").format(
				max(hours, 0), need_hours
			)
		)
	if ref.device_type and need_days:
		episode = _episode(doc)
		if not episode:
			met = False
			notes.append(_("No device episode linked (required at least {0} device days).").format(need_days))
		else:
			days = date_diff(getdate(doc.onset_date), getdate(episode.inserted_on))
			met = met and days >= need_days
			notes.append(
				_("Device in place {0} days before onset (required at least {1} days).").format(
					max(days, 0), need_days
				)
			)
	if not notes:
		return NOT_APPLICABLE, _("Definition {0} has no time thresholds.").format(ref.name)
	return (MET if met else NOT_MET), " ".join(notes)


def validate(doc):
	"""Gọi từ ``HAICase.validate``."""
	patient_code.apply(doc)
	if not doc.patient_code and not cint(doc.deidentified):
		frappe.throw(_("Enter the patient code; the patient name is never recorded."))
	if not doc.flags.tc_system:
		permissions.require_department(doc.department)
	_check_dates(doc)
	_attach_definition(doc)
	doc.reporting_period = periods.month_of(doc.onset_date)
	if not doc.flags.tc_system:
		periods.ensure_open(doc.onset_date, DOCTYPE, None if doc.is_new() else doc.name)
		if not doc.is_new():
			before = frappe.db.get_value(DOCTYPE, doc.name, "onset_date")
			periods.ensure_open(before, DOCTYPE, doc.name)
	_episode(doc)
	ssi.check_case_link(doc)  # FEAT-064 (A-147 f): ca phẫu thuật cùng người bệnh
	doc.time_check, doc.time_check_note = time_check(doc)
	_check_isolates(doc)
	if doc.docstatus == 0 and not doc.flags.tc_decision:
		doc.status = SUSPECTED


def _check_isolates(doc):
	seen = set()
	flags = []
	for row in doc.isolates or []:
		if row.isolate in seen:
			frappe.throw(_("Isolate {0} is listed twice.").format(row.isolate))
		seen.add(row.isolate)
		info = frappe.db.get_value(
			ISOLATE,
			row.isolate,
			["patient_code_hash", "mdro_flags", "organism_name", "collected_on"],
			as_dict=True,
		)
		if not info or (doc.patient_code_hash and info.patient_code_hash != doc.patient_code_hash):
			raise blocked(
				"HAI_CASE_ISOLATE_INVALID",
				_("Isolate not valid"),
				_("Isolate {0} belongs to another patient.").format(row.isolate),
				_("Choose an isolate of this patient."),
				items=["isolates"],
			)
		row.organism, row.collected_on, row.mdro_flags = (
			info.organism_name,
			info.collected_on,
			info.mdro_flags,
		)
		flags.append(info.mdro_flags)
	doc.mdro_flags = _flags(doc.mdro_flags, *flags)


def _require_decider():
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(DECIDE_ROLES):
		raise blocked(
			"HAI_CASE_NOT_ALLOWED",
			_("Not allowed"),
			_(
				"Only the infection control supervisor or the head of infection control can confirm or exclude a case."
			),
			_("Ask the infection control supervisor to review this case."),
		)


def before_submit(doc):
	if doc.status not in (CONFIRMED, EXCLUDED) or not doc.flags.tc_decision:
		raise blocked(
			"HAI_CASE_DECISION_REQUIRED",
			_("Decision required"),
			_("Case {0} is still suspected.").format(doc.name),
			_("Use Confirm case or Exclude case."),
		)
	_require_decider()
	if doc.status == EXCLUDED and not (doc.exclusion_reason or "").strip():
		raise _reason_required(_("A reason is required to exclude a case."))
	if doc.status == CONFIRMED and doc.time_check == NOT_MET and not (doc.exception_reason or "").strip():
		raise blocked(
			"HAI_CASE_EXCEPTION_REQUIRED",
			_("Time thresholds not met"),
			doc.time_check_note or _("The case does not meet the time thresholds of its definition."),
			_("Exclude the case, or enter an exception reason to confirm it."),
			items=["exception_reason"],
		)
	doc.confirmed_by = frappe.session.user
	doc.confirmed_on = now_datetime()


def _reason_required(reason):
	return blocked(
		"HAI_CASE_REASON_REQUIRED",
		_("Reason is required"),
		reason,
		_("Enter the reason and try again."),
		items=["exclusion_reason"],
	)


def before_update_after_submit(doc):
	before = doc.get_doc_before_save()
	if not doc.flags.tc_system:
		periods.ensure_open(doc.onset_date, DOCTYPE, doc.name)
	if before:
		changed = [
			field.fieldname
			for field in doc.meta.fields
			if field.fieldtype not in ("Table", "Section Break", "Column Break", "Password")
			and field.fieldname not in AFTER_SUBMIT
			and doc.get(field.fieldname) != before.get(field.fieldname)
		]
		if changed:
			frappe.throw(
				_("Case {0} is recorded; only the outcome and related isolates can change.").format(doc.name)
			)
	_check_isolates(doc)


def before_cancel(doc):
	periods.ensure_open(doc.onset_date, DOCTYPE, doc.name)


def on_trash(doc):
	frappe.throw(_("An HAI case is never deleted; exclude it with a reason instead."))


# --- thao tác -----------------------------------------------------------------------------------------------------


def decide(name, decision, reason=None, exception_reason=None):
	"""R11/R01 xác định hoặc loại trừ ca Nghi ngờ rồi ghi sổ (FR-M13-05). Trả doc."""
	_require_decider()
	if decision not in (CONFIRMED, EXCLUDED):
		frappe.throw(_("Choose Confirmed or Excluded."))
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.docstatus != 0:
		frappe.throw(_("Case {0} is already {1}.").format(name, _(doc.status)))
	periods.ensure_open(doc.onset_date, DOCTYPE, name)
	reason = " ".join(str(reason or "").split())
	exception = " ".join(str(exception_reason or "").split())
	if decision == EXCLUDED and not reason:
		raise _reason_required(_("A reason is required to exclude a case."))
	doc.status = decision
	if decision == EXCLUDED:
		doc.exclusion_reason = reason
	if exception:
		doc.exception_reason = exception
	doc.flags.tc_decision = True
	doc.flags.ignore_permissions = True
	doc.submit()
	if decision == CONFIRMED and doc.time_check == NOT_MET:
		audit.log(
			"Override",
			DOCTYPE,
			doc.name,
			new={"status": CONFIRMED, "time_check": NOT_MET},
			reason=doc.exception_reason,
		)
	return doc


def link_isolate(name, isolate):
	"""Gắn chủng vi sinh cùng người bệnh vào ca (Nháp hoặc đã ghi sổ)."""
	doc = frappe.get_doc(DOCTYPE, name)
	if any(row.isolate == isolate for row in doc.isolates):
		return doc
	doc.append("isolates", {"isolate": isolate})
	doc.flags.ignore_permissions = True
	doc.save()
	return doc


def on_mdro_detected(isolate):
	"""Hook ``tracecore_mdro_detected`` (FEAT-067): cộng nhãn đa kháng vào ca chưa hủy của cùng người bệnh."""
	hash_value = isolate.get("patient_code_hash")
	if not hash_value or not isolate.get("mdro_flags"):
		return
	for row in frappe.get_all(
		DOCTYPE,
		filters={"patient_code_hash": hash_value, "docstatus": ["<", 2]},
		fields=["name", "mdro_flags"],
	):
		merged = _flags(row.mdro_flags, isolate.get("mdro_flags"))
		if merged != row.mdro_flags:
			frappe.db.set_value(DOCTYPE, row.name, "mdro_flags", merged, update_modified=False)


# --- đọc ----------------------------------------------------------------------------------------------------------


def list_rows(filters=None, limit=100):
	"""Danh sách ca theo quyền người gọi; chỉ mã che (FR-M13-15)."""
	filters = {key: value for key, value in (filters or {}).items() if value not in (None, "")}
	rows = frappe.get_list(
		DOCTYPE,
		filters=filters,
		fields=list(LIST_FIELDS),
		order_by="onset_date desc, name desc",
		limit_page_length=limit,
	)
	return [dict(row) for row in rows]


def detail(name):
	if not frappe.has_permission(DOCTYPE, "read", name):
		raise frappe.PermissionError(_("You are not allowed to read case {0}.").format(name))
	row = frappe.db.get_value(DOCTYPE, name, list(DETAIL_FIELDS), as_dict=True)
	if row.device_episode:
		episode = frappe.db.get_value(
			EPISODE, row.device_episode, ["device_type", "inserted_on", "device_days"], as_dict=True
		)
		row["episode"] = dict(episode) if episode else None
	row["isolates"] = frappe.get_all(
		"HAI Case Isolate",
		filters={"parent": name, "parenttype": DOCTYPE},
		fields=["isolate", "organism", "collected_on", "mdro_flags"],
		order_by="idx",
	)
	ref = frappe.db.get_value(
		definitions.DOCTYPE, row.case_definition, list(definitions.THRESHOLDS), as_dict=True
	)
	row["thresholds"] = dict(ref) if ref else {}
	row["period_locked"] = periods.is_locked(row.reporting_period)
	return row


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: số ca Nghi ngờ chờ R11/R01 xác định (SCR-56)."""
	if not set(frappe.get_roles(user)) & set(DECIDE_ROLES):
		return {}
	return {"ca-nkbv": frappe.db.count(DOCTYPE, {"docstatus": 0})}
