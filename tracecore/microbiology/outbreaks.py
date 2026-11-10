"""Điều tra ổ dịch (FEAT-069; FR-M14-09, .1; BRU-MDR-004, BRU-HAI-005; UC-53 bước 1-4, A2, E1, E4; A-150 Q3, Q5).

- `open_outbreak` là đường duy nhất tạo `Outbreak Investigation` (ghi sổ ngay, Đang điều tra) — chỉ R01. Mở từ
  `Cluster Alert` thì điền sẵn khoa, tác nhân, ca và cảnh báo chuyển Investigation Opened.
- Ca gắn (R01/R11): `HAI Case` (M13, đọc qua ``frappe.db`` — không import M13), `Microbiology Isolate`, hoặc mã BN thêm
  tay (chỉ lưu bản che + hash, không lưu mã rõ). Trạng thái ca M13 đọc lại khi hiển thị: ca bị Loại trừ có nhãn (E4).
- Đường cong dịch theo ``onset_date`` (FR-M14-09.1): cột theo ngày, tách Xác định / Nghi ngờ / Loại trừ.
- Hành động kiểm soát: hook ``tracecore_outbreak_nc`` (M2 tạo `Incident CAPA` Outbreak Control và thêm `CAPA Action`);
  child `Outbreak CAPA` gắn NC đó và NC khác có sẵn (A2).
- Kết thúc (R01): bắt buộc tóm tắt; mọi NC gắn Closed/Cancelled hoặc có lý do (BRU-MDR-004, E1).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, date_diff, getdate, today

from tracecore.core import audit, extension, patient_code
from tracecore.core.errors import Block, BlockedError
from tracecore.microbiology import clusters, isolates

DOCTYPE = "Outbreak Investigation"
CASE_DOCTYPE = "Outbreak Case"
CAPA_DOCTYPE = "Outbreak CAPA"
HAI, ISOLATE, MANUAL = "HAI Case", "Microbiology Isolate", "Manual"
SOURCES = (HAI, ISOLATE, MANUAL)
CONFIRMED, SUSPECTED, EXCLUDED = "Confirmed", "Suspected", "Excluded"
CASE_STATES = (CONFIRMED, SUSPECTED, EXCLUDED)
DRAFT, INVESTIGATING, CONTROLLED, ENDED, CANCELLED = (
	"Draft",
	"Investigating",
	"Controlled",
	"Ended",
	"Cancelled",
)
ACTIVE = (INVESTIGATING, CONTROLLED)
OWNER_ROLES = ("TC R01",)  # mở, Đã kiểm soát, kết thúc, hủy (ảnh SCR-61: "Chỉ R01 mở/kết thúc ổ dịch")
WORK_ROLES = ("TC R01", "TC R11")  # gắn ca, hành động
NC_HOOK = "tracecore_outbreak_nc"
NC_CLOSED = ("Closed", "Cancelled")
DESK_LINK = "/app/tc-ksnk/o-dich"
CURVE_LEAD_DAYS = 2
CURVE_MAX_DAYS = 120
MAX_TEXT = 500


def _block(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _text(value, limit=MAX_TEXT) -> str:
	return " ".join(cstr(value).split())[:limit]


def _has(roles, user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(roles))


def can_own(user=None):
	return _has(OWNER_ROLES, user)


def can_work(user=None):
	return _has(WORK_ROLES, user)


def _require(roles, message):
	if not _has(roles):
		raise frappe.PermissionError(message)


# --- mở -----------------------------------------------------------------------------------------------------------


def _alert_cases(alert):
	refs = cstr(alert.case_refs).split()
	return [{"source_type": alert.source, "ref": ref} for ref in refs]


def prefill_from_alert(alert_name):
	"""Giá trị điền sẵn của form mở ổ dịch từ một cảnh báo cụm ca (không có mã BN)."""
	alert = frappe.get_doc(clusters.ALERT_DOCTYPE, alert_name)
	rule = (
		frappe.db.get_value(
			clusters.RULE_DOCTYPE, alert.rule, ["organism", "infection_site", "title"], as_dict=True
		)
		or frappe._dict()
	)
	return {
		"alert": alert.name,
		"status": alert.status,
		"department": alert.department,
		"department_name": alert.department_name or alert.department,
		"organism": rule.organism,
		"organism_or_disease": alert.key_label,
		"title": _("Cluster of {0} in {1}").format(
			alert.key_label, alert.department_name or alert.department
		),
		"source_label": _("{0} cases / {1} days").format(alert.case_count, alert.window_days),
		"cases": _alert_cases(alert),
	}


def _required(values):
	missing = [
		key
		for key in ("title", "organism_or_disease", "department", "start_date")
		if not _text(values.get(key))
	]
	if missing:
		raise _block(
			"OUTBREAK_FIELDS_REQUIRED",
			_("Outbreak investigation not opened"),
			_("Title, organism or disease, department and start date are required."),
			_("Fill in the required fields, then open the investigation."),
		)
	if getdate(values["start_date"]) > getdate(today()):
		raise _block(
			"OUTBREAK_DATE_INVALID",
			_("Date not valid"),
			_("The start date cannot be in the future."),
			_("Check the date, then save again."),
		)


def open_outbreak(values: dict):
	"""R01 mở và ghi sổ một điều tra ổ dịch; trả Document."""
	_require(OWNER_ROLES, _("Only the head of infection control opens an outbreak investigation."))
	values = dict(values or {})
	alert = None
	if values.get("cluster_alert"):
		alert = clusters._new_alert(values["cluster_alert"])
		values["department"] = values.get("department") or alert.department
	_required(values)
	departments = [
		{"department": name}
		for name in dict.fromkeys(values.get("departments") or [])
		if name and name != values["department"]
	]
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"title": _text(values["title"], 140),
			"organism_or_disease": _text(values["organism_or_disease"], 140),
			"organism": values.get("organism") or None,
			"communicable_disease": values.get("communicable_disease") or None,
			"department": values["department"],
			"departments": departments,
			"start_date": getdate(values["start_date"]),
			"source": "Cluster Alert" if alert else (values.get("source") or "Suspicion"),
			"cluster_alert": alert.name if alert else None,
			"opened_by": frappe.session.user,
			"case_definition": _text(values.get("case_definition"), 2000) or None,
		}
	)
	if alert:
		for row in _alert_cases(alert):
			doc.append("cases", _case_row(row["source_type"], row["ref"]))
	doc.flags.tc_outbreak = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	if alert:
		clusters.mark_opened(alert.name, doc.name)
	return doc


# --- controller ---------------------------------------------------------------------------------------------------


def validate(doc):
	if doc.is_new() and not doc.flags.tc_outbreak:
		frappe.throw(_("Outbreak investigations are opened on the outbreak screen."))
	if doc.docstatus == 0:
		doc.status = DRAFT
	elif doc.docstatus == 1 and doc.status in (None, "", DRAFT):
		doc.status = INVESTIGATING


def guard_after_submit(doc):
	if not doc.flags.tc_outbreak:
		frappe.throw(_("Update the outbreak investigation on the outbreak screen."))


def on_cancel(doc):
	doc.db_set("status", CANCELLED, update_modified=False)


def _active(name):
	if not name or not frappe.db.exists(DOCTYPE, name):
		raise frappe.DoesNotExistError(_("Outbreak investigation {0} does not exist.").format(name))
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.docstatus != 1 or doc.status not in ACTIVE:
		raise _block(
			"OUTBREAK_NOT_ACTIVE",
			_("Outbreak investigation closed"),
			_("Outbreak investigation {0} is {1}.").format(doc.name, _(doc.status)),
			_("Refresh the outbreak screen."),
		)
	return doc


def _save(doc):
	doc.flags.tc_outbreak = True
	doc.save(ignore_permissions=True)  # vai trò đã kiểm ở dịch vụ
	return doc


# --- ca -----------------------------------------------------------------------------------------------------------


def _hai_state(row):
	if cint(row.docstatus) == 2:
		return EXCLUDED
	return row.status if row.status in CASE_STATES else SUSPECTED


def _case_row(source_type, ref=None, code=None, onset_date=None, case_status=None, department=None):
	if source_type == HAI:
		row = (
			frappe.db.get_value(
				HAI,
				ref,
				[
					"name",
					"patient_code_masked",
					"patient_code_hash",
					"department",
					"onset_date",
					"status",
					"docstatus",
					"infection_site",
				],
				as_dict=True,
			)
			if ref
			else None
		)
		if not row:
			raise _case_invalid(_("HAI case {0} does not exist.").format(ref))
		return {
			"source_type": HAI,
			"hai_case": row.name,
			"patient_code_masked": row.patient_code_masked,
			"patient_code_hash": row.patient_code_hash,
			"department": row.department,
			"onset_date": row.onset_date,
			"case_status": _hai_state(row),
			"label": _(row.infection_site) if row.infection_site else None,
			"added_by": frappe.session.user,
		}
	if source_type == ISOLATE:
		row = (
			frappe.db.get_value(
				isolates.DOCTYPE,
				ref,
				[
					"name",
					"patient_code_masked",
					"patient_code_hash",
					"department",
					"collected_on",
					"organism_name",
					"mdro_flags",
				],
				as_dict=True,
			)
			if ref
			else None
		)
		if not row:
			raise _case_invalid(_("Isolate {0} does not exist.").format(ref))
		label = " — ".join(value for value in (row.organism_name, row.mdro_flags) if value)
		return {
			"source_type": ISOLATE,
			"isolate": row.name,
			"patient_code_masked": row.patient_code_masked,
			"patient_code_hash": row.patient_code_hash,
			"department": row.department,
			"onset_date": row.collected_on,
			"case_status": CONFIRMED,
			"label": label or None,
			"added_by": frappe.session.user,
		}
	if source_type == MANUAL:
		text = patient_code.normalise(code)
		if not text or not onset_date:
			raise _case_invalid(_("A case added by hand needs the patient code and the onset date."))
		if getdate(onset_date) > getdate(today()):
			raise _case_invalid(_("The onset date cannot be in the future."))
		return {
			"source_type": MANUAL,
			"patient_code_masked": patient_code.mask(text),
			"patient_code_hash": patient_code.hash_of(text),
			"department": department or None,
			"onset_date": getdate(onset_date),
			"case_status": case_status if case_status in CASE_STATES else SUSPECTED,
			"added_by": frappe.session.user,
		}
	raise _case_invalid(_("Choose the case source: HAI case, isolate or patient code."))


def _case_invalid(reason):
	return _block(
		"OUTBREAK_CASE_INVALID",
		_("Case not added"),
		reason,
		_("Check the case, then add it again."),
	)


def add_case(
	name, source_type, ref=None, patient_code=None, onset_date=None, case_status=None, department=None
):
	"""R01/R11 gắn một ca vào ổ dịch đang mở (UC-53 bước 2)."""
	_require(WORK_ROLES, _("Only infection control staff can link cases to an outbreak."))
	doc = _active(name)
	row = _case_row(source_type, ref, patient_code, onset_date, case_status, department)
	for existing in doc.cases:
		same = (
			(row.get("hai_case") and existing.hai_case == row["hai_case"])
			or (row.get("isolate") and existing.isolate == row["isolate"])
			or (
				source_type == MANUAL
				and existing.source_type == MANUAL
				and existing.patient_code_hash == row["patient_code_hash"]
			)
		)
		if same:
			raise _block(
				"OUTBREAK_CASE_DUPLICATE",
				_("Case already linked"),
				_("This case is already in outbreak {0}.").format(doc.name),
				_("Choose another case."),
			)
	doc.append("cases", row)
	return _save(doc)


def remove_case(name, row_name, reason=None):
	_require(WORK_ROLES, _("Only infection control staff can unlink cases from an outbreak."))
	text = _text(reason)
	if not text:
		raise _block(
			"OUTBREAK_REASON_REQUIRED",
			_("Reason required"),
			_("A reason is required to remove a case from the outbreak."),
			_("Enter why the case is removed."),
		)
	doc = _active(name)
	rows = [row for row in doc.cases if row.name != row_name]
	if len(rows) == len(doc.cases):
		raise frappe.DoesNotExistError(_("Case row {0} is not in outbreak {1}.").format(row_name, name))
	doc.set("cases", rows)
	_save(doc)
	audit.log("Update", DOCTYPE, doc.name, reason=_("Case removed: {0}").format(text))
	return doc


def _live_states(rows):
	names = [row.hai_case for row in rows if row.hai_case]
	if not names:
		return {}
	return {
		row.name: _hai_state(row)
		for row in frappe.get_all(
			HAI, filters={"name": ["in", names]}, fields=["name", "status", "docstatus"]
		)
	}


def case_rows(doc):
	live = _live_states(doc.cases)
	result = []
	for row in sorted(doc.cases, key=lambda item: (getdate(item.onset_date), item.idx)):
		state = live.get(row.hai_case, row.case_status) if row.hai_case else row.case_status
		result.append(
			{
				"row": row.name,
				"source_type": row.source_type,
				"ref": row.hai_case or row.isolate,
				"patient_code_masked": row.patient_code_masked,
				"department": row.department,
				"onset_date": getdate(row.onset_date),
				"state": state or SUSPECTED,
				"excluded_at_source": bool(row.hai_case) and state == EXCLUDED,
				"label": row.label,
			}
		)
	return result


def epi_curve(doc, until=None):
	"""Đường cong dịch theo ngày khởi phát (FR-M14-09.1): ``{from, to, max, days: [{date, confirmed, suspected,
	excluded}]}``; trục từ 2 ngày trước ca đầu tiên đến hôm nay (hoặc ngày kết thúc), tối đa 120 ngày."""
	rows = case_rows(doc)
	if not rows:
		return {"from": None, "to": None, "max": 0, "days": []}
	first = min(row["onset_date"] for row in rows)
	last = max(row["onset_date"] for row in rows)
	end = getdate(until or doc.end_date or today())
	end = max(end, last)
	start = add_days(first, -CURVE_LEAD_DAYS)
	if date_diff(end, start) >= CURVE_MAX_DAYS:
		start = add_days(end, -(CURVE_MAX_DAYS - 1))
	counts = {}
	for row in rows:
		bucket = counts.setdefault(str(row["onset_date"]), {CONFIRMED: 0, SUSPECTED: 0, EXCLUDED: 0})
		bucket[row["state"]] = bucket.get(row["state"], 0) + 1
	days = []
	day = start
	while day <= end:
		bucket = counts.get(str(day), {})
		days.append(
			{
				"date": str(day),
				"confirmed": bucket.get(CONFIRMED, 0),
				"suspected": bucket.get(SUSPECTED, 0),
				"excluded": bucket.get(EXCLUDED, 0),
			}
		)
		day = add_days(day, 1)
	peak = max((item["confirmed"] + item["suspected"] + item["excluded"] for item in days), default=0)
	return {"from": str(start), "to": str(end), "max": peak, "days": days}


# --- hành động (Incident CAPA) ------------------------------------------------------------------------------------


def _main_nc(doc):
	return next((row.incident_capa for row in doc.capas if cint(row.is_main)), None)


def add_action(name, description=None, responsible=None, due_date=None):
	"""R01/R11 thêm hành động kiểm soát: NC Outbreak Control (tạo lần đầu qua hook M2) + một CAPA Action."""
	_require(WORK_ROLES, _("Only infection control staff can add outbreak control actions."))
	doc = _active(name)
	text = _text(description)
	if not text or not responsible or not due_date or not frappe.db.exists("User", responsible):
		raise _block(
			"OUTBREAK_ACTION_INCOMPLETE",
			_("Action is incomplete"),
			_("Every action needs a description, a responsible person and a due date."),
			_("Complete the action, then add it again."),
		)
	ctx = {
		"outbreak": doc.name,
		"department": doc.department,
		"description": _("Outbreak control: {0} ({1})").format(doc.title, doc.name),
		"action": {"description": text, "responsible": responsible, "due_date": getdate(due_date)},
	}
	results = extension.run(NC_HOOK, ctx)
	incident = results[0] if results else None
	if not incident:
		frappe.throw(_("No module handles outbreak control incidents."))
	if not any(row.incident_capa == incident for row in doc.capas):
		doc.append("capas", {"incident_capa": incident, "is_main": 1})
		_save(doc)
	return doc


def link_nc(name, incident):
	"""Gắn một Incident CAPA có sẵn (vd NC môi trường lấy mẫu trong điều tra — UC-53 A2)."""
	_require(WORK_ROLES, _("Only infection control staff can link incidents to an outbreak."))
	doc = _active(name)
	if not incident or not frappe.db.exists("Incident CAPA", incident):
		raise frappe.DoesNotExistError(_("Incident {0} does not exist.").format(incident))
	if any(row.incident_capa == incident for row in doc.capas):
		raise _block(
			"OUTBREAK_NC_DUPLICATE",
			_("Incident already linked"),
			_("Incident {0} is already linked to outbreak {1}.").format(incident, doc.name),
			_("Choose another incident."),
		)
	doc.append("capas", {"incident_capa": incident, "is_main": 0})
	return _save(doc)


def action_rows(doc):
	"""Hành động của mọi NC gắn ổ dịch: mô tả, người, hạn, trạng thái (Done / Open / Overdue) + trạng thái NC."""
	names = [row.incident_capa for row in doc.capas]
	if not names:
		return [], []
	ncs = {
		row.name: row
		for row in frappe.get_all(
			"Incident CAPA",
			filters={"name": ["in", names]},
			fields=["name", "status", "incident_type", "description"],
		)
	}
	actions = frappe.get_all(
		"CAPA Action",
		filters={"parent": ["in", names], "parenttype": "Incident CAPA"},
		fields=[
			"name",
			"parent",
			"description",
			"responsible",
			"responsible_name",
			"due_date",
			"status",
			"result",
		],
		order_by="parent asc, idx asc",
	)
	day = getdate(today())
	rows = []
	for action in actions:
		state = (
			"Done"
			if action.status == "Done"
			else ("Overdue" if action.due_date and getdate(action.due_date) < day else "Open")
		)
		rows.append({**action, "incident": action.parent, "state": state})
	incidents = [
		{
			"row": row.name,
			"incident": row.incident_capa,
			"is_main": cint(row.is_main),
			"status": (ncs.get(row.incident_capa) or {}).get("status"),
			"incident_type": (ncs.get(row.incident_capa) or {}).get("incident_type"),
			"open_reason": row.open_reason,
			"closed": (ncs.get(row.incident_capa) or {}).get("status") in NC_CLOSED,
		}
		for row in doc.capas
	]
	return rows, incidents


# --- trạng thái ---------------------------------------------------------------------------------------------------


def set_controlled(name):
	_require(OWNER_ROLES, _("Only the head of infection control marks an outbreak as controlled."))
	doc = _active(name)
	if doc.status != INVESTIGATING:
		raise _block(
			"OUTBREAK_NOT_ACTIVE",
			_("Outbreak already controlled"),
			_("Outbreak investigation {0} is {1}.").format(doc.name, _(doc.status)),
			_("Refresh the outbreak screen."),
		)
	doc.status = CONTROLLED
	doc.controlled_on = getdate(today())
	return _save(doc)


def end_outbreak(name, summary=None, end_date=None, external_report_ref=None, open_reasons=None):
	"""R01 kết thúc ổ dịch (BRU-MDR-004): cần tóm tắt; mọi NC gắn đã đóng/hủy hoặc có lý do."""
	_require(OWNER_ROLES, _("Only the head of infection control ends an outbreak investigation."))
	doc = _active(name)
	text = cstr(summary).strip()[:5000]
	if not text:
		raise _block(
			"OUTBREAK_SUMMARY_REQUIRED",
			_("Outbreak not ended"),
			_("A summary is required to end the outbreak investigation."),
			_("Write the summary, then end the outbreak."),
		)
	end = getdate(end_date or today())
	if end > getdate(today()) or end < getdate(doc.start_date):
		raise _block(
			"OUTBREAK_DATE_INVALID",
			_("Date not valid"),
			_("The end date must be between the start date and today."),
			_("Check the date, then end the outbreak again."),
		)
	reasons = {key: _text(value) for key, value in (open_reasons or {}).items() if _text(value)}
	statuses = dict(
		frappe.get_all(
			"Incident CAPA",
			filters={"name": ["in", [row.incident_capa for row in doc.capas] or [""]]},
			fields=["name", "status"],
			as_list=True,
		)
	)
	still_open = []
	for row in doc.capas:
		if row.name in reasons:
			row.open_reason = reasons[row.name]
		if statuses.get(row.incident_capa) not in NC_CLOSED and not _text(row.open_reason):
			still_open.append(row.incident_capa)
	if still_open:
		raise _block(
			"OUTBREAK_CAPA_OPEN",
			_("Outbreak not ended"),
			_("Incidents still open without a reason: {0}.").format(", ".join(still_open)),
			_("Close the incidents, or enter why each one stays open, then end the outbreak."),
		)
	doc.update(
		{
			"status": ENDED,
			"end_date": end,
			"summary": text,
			"external_report_ref": _text(external_report_ref, 140) or None,
		}
	)
	return _save(doc)


def cancel_outbreak(name, reason=None):
	_require(OWNER_ROLES, _("Only the head of infection control cancels an outbreak investigation."))
	text = _text(reason)
	if not text:
		raise _block(
			"OUTBREAK_REASON_REQUIRED",
			_("Outbreak not cancelled"),
			_("A reason is required to cancel an outbreak investigation."),
			_("Enter why the investigation is cancelled."),
		)
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.docstatus != 1:
		raise _block(
			"OUTBREAK_NOT_ACTIVE",
			_("Outbreak investigation closed"),
			_("Outbreak investigation {0} is {1}.").format(doc.name, _(doc.status)),
			_("Refresh the outbreak screen."),
		)
	doc.flags.ignore_permissions = True
	doc.cancel()
	audit.log("Cancel", DOCTYPE, doc.name, reason=text)
	doc.reload()
	return doc


# --- đọc ----------------------------------------------------------------------------------------------------------

SUMMARY_FIELDS = (
	"name",
	"title",
	"organism_or_disease",
	"department",
	"department_name",
	"start_date",
	"status",
	"controlled_on",
	"end_date",
	"source",
)


def summary_rows(limit=100):
	"""Danh sách ổ dịch tổng hợp (không dữ liệu cá nhân — R13 xem được): số ca, số NC còn mở."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={"docstatus": 1},
		fields=list(SUMMARY_FIELDS),
		order_by="start_date desc, creation desc",
		limit_page_length=limit,
	)
	names = [row.name for row in rows] or [""]
	counts = dict(
		frappe.get_all(
			CASE_DOCTYPE,
			filters={"parent": ["in", names], "parenttype": DOCTYPE},
			fields=["parent", "count(name) as n"],
			group_by="parent",
			as_list=True,
		)
	)
	for row in rows:
		row["case_count"] = cint(counts.get(row.name))
		row["days"] = date_diff(row.end_date or today(), row.start_date) + 1
	return [dict(row) for row in rows]


def detail(name):
	"""Chi tiết một ổ dịch cho R01/R11 (mã BN chỉ dạng che)."""
	doc = frappe.get_doc(DOCTYPE, name)
	actions, incidents = action_rows(doc)
	return {
		"name": doc.name,
		"title": doc.title,
		"organism_or_disease": doc.organism_or_disease,
		"organism": doc.organism,
		"communicable_disease": doc.communicable_disease,
		"department": doc.department,
		"department_name": doc.department_name or doc.department,
		"departments": [row.department for row in doc.departments],
		"start_date": doc.start_date,
		"source": doc.source,
		"cluster_alert": doc.cluster_alert,
		"opened_by": doc.opened_by,
		"opened_by_name": frappe.utils.get_fullname(doc.opened_by) if doc.opened_by else None,
		"case_definition": doc.case_definition,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"controlled_on": doc.controlled_on,
		"end_date": doc.end_date,
		"summary": doc.summary,
		"external_report_ref": doc.external_report_ref,
		"cases": case_rows(doc),
		"curve": epi_curve(doc),
		"actions": actions,
		"incidents": incidents,
		"opened_at": doc.creation,
	}
