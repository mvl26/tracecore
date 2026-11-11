"""Sự cố nghi ngộ độc thực phẩm (FEAT-073; FR-M17-04, FR-M17-04.1; BRU-FS-002; UC-56 bước 4, E2, A2; A-151 Q1, Q2, Q4).

- Ghi sổ ``Foodborne Event`` → báo ngay R01, R11 (``FOODBORNE_EVENT_REPORTED``, khẩn), ``nc_status`` = Đề nghị.
- Ngộ độc luôn xem như ổ dịch tiềm năng (BRU-FS-002): ``affected_count`` ≥ ``IC Program Settings.
  foodborne_outbreak_threshold`` → ``outbreak_status`` = Đề nghị. Ngưỡng trống → chỉ đề nghị NC, nhắc R01 đặt ngưỡng
  (UC-56 E2). Ngưỡng dùng được chụp vào ``threshold_applied``.
- R01/R11 ``open_nc`` → hook ``tracecore_food_safety_nc`` (M2 tạo Incident CAPA loại Food Safety; M17 không import M2)
  hoặc ``dismiss_nc`` có lý do. Ổ dịch: R01/R11 mở `Outbreak Investigation` (M14) trên Desk với ``outbreak_prefill``;
  ``on_outbreak_saved`` (doc_events của M14) ghi ngược tên ổ dịch khi nguồn là sự cố này; hoặc ``dismiss_outbreak``.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, formatdate, getdate, today

from tracecore.core import audit, extension, notification
from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Foodborne Event"
SETTINGS = "IC Program Settings"
THRESHOLD_FIELD = "foodborne_outbreak_threshold"
SUGGESTED, OPENED, DISMISSED = "Suggested", "Opened", "Dismissed"
NC_HOOK = "tracecore_food_safety_nc"
REPORTED_EVENT = "FOODBORNE_EVENT_REPORTED"
THRESHOLD_EVENT = "FOODBORNE_THRESHOLD_MISSING"
DECIDER_ROLES = frozenset({"TC R01", "TC R11", "System Manager"})
OUTBREAK_DOCTYPE = "Outbreak Investigation"


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def threshold():
	return cint(frappe.db.get_single_value(SETTINGS, THRESHOLD_FIELD))


def validate(doc):
	"""Gọi từ ``FoodborneEvent.validate``."""
	if cint(doc.affected_count) < 1:
		raise _blocked(
			"FOODBORNE_COUNT_INVALID",
			_("Number of people affected is required"),
			_("A suspected food poisoning event needs at least one affected person."),
			_("Enter how many people are affected (staff, patients, families)."),
		)
	doc.event_date = getdate(doc.event_date or today())
	if doc.event_date > getdate(today()):
		raise _blocked(
			"FOODBORNE_DATE_INVALID",
			_("Event date in the future"),
			_("Event date {0} is after today.").format(formatdate(doc.event_date)),
			_("Enter the day the people fell ill."),
		)


def before_submit(doc):
	limit = threshold()
	doc.threshold_applied = limit
	doc.nc_status = SUGGESTED
	doc.outbreak_status = SUGGESTED if limit and cint(doc.affected_count) >= limit else None


def _summary(doc):
	return _("{0} people affected at {1} on {2}; suspected food: {3}.").format(
		doc.affected_count, doc.location, formatdate(doc.event_date), doc.suspected_food or "-"
	)


def on_submit(doc):
	"""Báo ngay R01, R11 (FR-M17-04); ngưỡng chưa đặt → nhắc R01 (UC-56 E2)."""
	notification.emit(
		REPORTED_EVENT,
		doc,
		subject=_("Suspected food poisoning {0}").format(doc.name),
		message=_summary(doc),
	)
	if not doc.threshold_applied:
		notification.emit(
			THRESHOLD_EVENT,
			doc,
			subject=_("Set the people threshold for food poisoning outbreaks"),
			message=_(
				"Event {0} could not be checked for an outbreak because no people threshold is set in IC Program Settings."
			).format(doc.name),
		)


# --- quyết định của R01/R11 ---------------------------------------------------------------------------------------


def can_decide(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & DECIDER_ROLES)


def _require_decider():
	if not can_decide():
		frappe.throw(
			_("Only R01 or R11 can decide on a food poisoning event."),
			frappe.PermissionError,
		)


def _posted(name):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	if doc.docstatus != 1:
		raise _blocked(
			"FOODBORNE_NOT_SUGGESTED",
			_("Event not posted"),
			_("Event {0} is not posted.").format(name),
			_("Post the event first."),
		)
	return doc


def _reason(reason):
	reason = cstr(reason).strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason required"),
			_("No reason was given."),
			_("Enter why it is not needed."),
		)
	return reason


def _not_suggested(name, what):
	return _blocked(
		"FOODBORNE_NOT_SUGGESTED",
		_("Nothing to decide"),
		_("Event {0} has no {1} waiting for a decision.").format(name, what),
		_("Refresh the screen to see the current state."),
	)


def open_nc(name):
	"""Tạo (hoặc trả) Incident Food Safety liên kết sự cố; trả tên Incident."""
	_require_decider()
	doc = _posted(name)
	if doc.nc_status == OPENED and doc.incident_capa:
		return doc.incident_capa
	if doc.nc_status != SUGGESTED:
		raise _not_suggested(name, _("non-conformance"))
	ctx = {
		"event": doc.name,
		"department": doc.department,
		"description": _("Suspected food poisoning {0}: {1}").format(doc.name, _summary(doc)),
	}
	results = [result for result in extension.run(NC_HOOK, ctx) if result]
	if not results:
		frappe.throw(_("No module handles non-conformances from food poisoning events."))
	doc.db_set({"nc_status": OPENED, "incident_capa": results[0]})
	return results[0]


def dismiss_nc(name, reason):
	_require_decider()
	reason = _reason(reason)
	doc = _posted(name)
	if doc.nc_status != SUGGESTED:
		raise _not_suggested(name, _("non-conformance"))
	doc.db_set({"nc_status": DISMISSED, "nc_reason": reason})
	audit.log(
		"Update", DOCTYPE, name, old={"nc_status": SUGGESTED}, new={"nc_status": DISMISSED}, reason=reason
	)


def dismiss_outbreak(name, reason):
	_require_decider()
	reason = _reason(reason)
	doc = _posted(name)
	if doc.outbreak_status != SUGGESTED:
		raise _not_suggested(name, _("outbreak investigation"))
	doc.db_set({"outbreak_status": DISMISSED, "outbreak_reason": reason})
	audit.log(
		"Update",
		DOCTYPE,
		name,
		old={"outbreak_status": SUGGESTED},
		new={"outbreak_status": DISMISSED},
		reason=reason,
	)


def outbreak_ready():
	"""M14 đã có DocType ổ dịch (FEAT-069) thì màn mới hiện nút mở điều tra (A-151 Q1)."""
	return bool(frappe.db.exists("DocType", OUTBREAK_DOCTYPE))


def outbreak_prefill(name):
	"""Giá trị điền sẵn form `Outbreak Investigation` mới mở từ sự cố."""
	_require_decider()
	doc = _posted(name)
	return {
		"title": _("Suspected food poisoning {0} - {1}").format(doc.name, doc.location),
		"start_date": doc.event_date,
		"source": "Foodborne Event",  # lựa chọn "Phát hiện từ" của ổ dịch M14 (FEAT-069)
		"source_doctype": DOCTYPE,
		"source_name": doc.name,
	}


def outbreak_source_prefill(source_doctype, source_name):
	"""Hook ``tracecore_outbreak_source_prefill`` của M14 (A-151 Q1): điền sẵn form mở ổ dịch trên SCR-61 từ sự cố."""
	if source_doctype != DOCTYPE or not frappe.db.exists(DOCTYPE, source_name):
		return None
	values = outbreak_prefill(source_name)
	department = frappe.db.get_value(DOCTYPE, source_name, "department")
	return {
		**values,
		"start_date": str(values["start_date"]) if values.get("start_date") else None,
		"organism_or_disease": _("Suspected food poisoning"),
		"department": department,
		"department_name": frappe.db.get_value("Department", department, "department_name")
		if department
		else None,
	}


def on_outbreak_saved(doc, method=None):
	"""``doc_events["Outbreak Investigation"]``: ổ dịch có nguồn là sự cố → ghi ngược tên, Đã mở (liên kết hai chiều)."""
	if doc.get("source_doctype") != DOCTYPE or not doc.get("source_name"):
		return
	if not frappe.db.exists(DOCTYPE, doc.source_name):
		return
	frappe.db.set_value(
		DOCTYPE,
		doc.source_name,
		{"outbreak_investigation": doc.name, "outbreak_status": OPENED},
		update_modified=False,
	)


def pending_count():
	"""Sự cố chờ quyết định NC hoặc ổ dịch."""
	return len(
		frappe.get_all(
			DOCTYPE,
			filters={"docstatus": 1},
			or_filters={"nc_status": SUGGESTED, "outbreak_status": SUGGESTED},
			pluck="name",
		)
	)
