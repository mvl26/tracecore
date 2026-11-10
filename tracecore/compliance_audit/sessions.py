"""Phiếu giám sát `Audit Session` (FEAT-060; ADR-015, FR-M12-04/06/08/10/11, BRU-AUD-001/004/005, A-134).

- Tạo phiếu chỉ từ phiên bản mẫu đang hiệu lực (BRU-AUD-001); mục của mẫu chép vào ``answers`` (bản chụp) và không sửa
  được sau đó, nên đổi mẫu không đổi phiếu cũ.
- Người giám sát không là người được quan sát, của phiếu hay của từng cơ hội (BRU-AUD-004, FR-M12-10).
- Điểm/kết quả tính ở server theo ``scoring_method`` (``scoring``); ghi sổ: cỡ mẫu khoa-tháng (FR-M12-11), đề nghị NC
  khi mục trọng yếu không đạt (BRU-AUD-005), phản hồi khoa (``feedback``).
- R08/R12 chỉ đọc/ghi phiếu của khoa có User Permission Department (FR-M12-08.1, NFR-SEC-09).
"""

import frappe
from frappe import _
from frappe.utils import cint, get_first_day, get_last_day, getdate, now_datetime

from tracecore.compliance_audit import (  # FEAT-061: hand_hygiene; FEAT-062: bundle
	bundle,
	feedback,
	hand_hygiene,
	scoring,
	templates,
)
from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Audit Session"
SNAPSHOT_FIELDS = ("item_code", "section", "question", "answer_type", "weight", "is_critical")
ANSWER_FIELDS = ("answer", "value", "photo", "note")
WIDE_ROLES = frozenset({"TC R01", "TC R02", "TC R11", "System Manager"})
DEPT_ROLES = frozenset({"TC R08", "TC R12"})
SUGGESTED = "Suggested"


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


# --- tạo và kiểm phiếu ------------------------------------------------------------------------------------------


def _check_template(doc):
	template = frappe.db.get_value(
		templates.DOCTYPE, doc.audit_template, ["template_code", "docstatus", "effective_from"], as_dict=True
	)
	active = (
		template
		and template.docstatus == 1
		and templates.active_version(template.template_code, doc.audit_date)
	)
	if (
		doc.flags.tc_replay
		and template
		and template.docstatus == 1
		and getdate(template.effective_from) <= getdate(doc.audit_date)
	):
		return  # phiếu offline giữ phiên bản tại lúc tạo dù mẫu đã lên phiên bản mới (UC-44 E3)
	if active != doc.audit_template:
		raise blocked(
			"AUDIT_TEMPLATE_NOT_APPROVED",
			_("Template version not in use"),
			_("Template {0} is not the approved version in effect on {1}.").format(
				doc.audit_template, frappe.format(doc.audit_date, "Date")
			),
			_("Open the audit again to use the current approved version{0}.").format(
				f" ({active})" if active else ""
			),
		)


def _snapshot(doc):
	"""Chép mục của phiên bản mẫu vào ``answers``; câu trả lời gửi kèm ghép theo ``item_code``."""
	given = {}
	for row in doc.answers or ():
		code = (row.item_code or "").strip().upper()
		if code:
			given[code] = row
	items = frappe.get_all(
		templates.ITEM_DOCTYPE,
		filters={"parent": doc.audit_template, "parenttype": templates.DOCTYPE},
		fields=list(SNAPSHOT_FIELDS),
		order_by="idx asc",
	)
	unknown = sorted(set(given) - {item.item_code for item in items})
	if unknown:
		raise blocked(
			"AUDIT_ITEM_UNKNOWN",
			_("Item not in template"),
			_("Items {0} are not in template {1}.").format(", ".join(unknown), doc.audit_template),
			_("Reload the audit form and answer again."),
		)
	doc.set("answers", [])
	for item in items:
		answer = given.get(item.item_code)
		doc.append(
			"answers",
			{
				**{field: item.get(field) for field in SNAPSHOT_FIELDS},
				**{field: answer.get(field) for field in ANSWER_FIELDS if answer is not None},
			},
		)


def _guard_snapshot(doc):
	before = doc.get_doc_before_save()
	if not before:
		return
	old = [tuple(row.get(field) for field in SNAPSHOT_FIELDS) for row in before.answers]
	new = [tuple(row.get(field) for field in SNAPSHOT_FIELDS) for row in doc.answers]
	if [tuple(map(str, row)) for row in old] != [tuple(map(str, row)) for row in new]:
		frappe.throw(
			_("Audit items come from template version {0} and cannot be changed.").format(doc.audit_template)
		)


def _self_observation():
	return blocked(
		"AUDIT_SELF_OBSERVATION",
		_("Cannot audit yourself"),
		_("The observed person is the observer."),
		_("Choose another observed person, or ask another auditor to observe you."),
	)


def _check_people(doc):
	if doc.subject_employee and doc.subject_employee == doc.observer:
		raise _self_observation()
	for row in doc.opportunities or ():
		if row.subject_employee and row.subject_employee == doc.observer:
			raise _self_observation()


def _default_observer(doc):
	if not doc.observer:
		doc.observer = frappe.db.get_value(
			"Employee", {"user_id": frappe.session.user, "status": "Active"}, "name"
		)


def validate(doc):
	"""Gọi từ ``AuditSession.validate``."""
	_default_observer(doc)
	if doc.is_new():
		doc.audit_date = doc.audit_date or getdate()
		_check_template(doc)
		_snapshot(doc)
	else:
		_guard_snapshot(doc)
	_check_people(doc)
	template = frappe.db.get_value(templates.DOCTYPE, doc.audit_template, ["pass_threshold"], as_dict=True)
	doc.scoring_method = frappe.db.get_value(templates.DOCTYPE, doc.audit_template, "scoring_method")
	hand_hygiene.validate(doc)  # FEAT-061: cơ hội vệ sinh tay (BRU-AUD-002)
	bundle.validate(doc)  # FEAT-062: phiếu gói dự phòng gắn đợt thiết bị (FR-M12-07)
	doc.score_pct, doc.result, critical = scoring.score(doc, template or frappe._dict())
	doc.critical_failed = 1 if critical else 0


def before_submit(doc):
	hand_hygiene.before_submit(doc)  # FEAT-061: phiếu theo cơ hội cần ≥ 1 cơ hội
	missing = [
		row.item_code
		for row in doc.answers
		if row.answer_type == scoring.BINARY_ITEM
		and row.answer not in (scoring.PASS, scoring.FAIL, scoring.NA)
	]
	if missing:
		raise blocked(
			"AUDIT_ANSWER_MISSING",
			_("Items not answered"),
			_("Items {0} have no answer.").format(", ".join(missing)),
			_("Choose Pass, Fail or N/A for every item, then post the audit."),
			items=missing,
		)
	no_note = [
		row.item_code
		for row in doc.answers
		if row.answer == scoring.FAIL and not (row.note or "").strip() and not row.photo
	]
	if no_note:
		raise blocked(
			"AUDIT_FAIL_NOTE_REQUIRED",
			_("Note required for failed items"),
			_("Failed items {0} have no note or photo.").format(", ".join(no_note)),
			_("Add a short note or a photo to each failed item."),
			items=no_note,
		)
	doc.ended_at = doc.ended_at or now_datetime()


def month_sample(template_code, department, on):
	"""Số phiếu đã ghi sổ của mã mẫu tại khoa trong tháng của ngày ``on`` (FR-M12-11)."""
	on = getdate(on)
	return frappe.db.count(
		DOCTYPE,
		{
			"template_code": template_code,
			"department": department,
			"docstatus": 1,
			"audit_date": ["between", [get_first_day(on), get_last_day(on)]],
		},
	)


def on_submit(doc):
	min_sample = cint(frappe.db.get_value(templates.DOCTYPE, doc.audit_template, "min_sample"))
	if (
		doc.scoring_method == templates.BY_OPPORTUNITY
	):  # FEAT-061: cỡ mẫu = số cơ hội của khoa-tháng (FR-M12-11)
		sample = hand_hygiene.month_opportunities(doc.template_code, doc.department, doc.audit_date)
	else:
		sample = month_sample(doc.template_code, doc.department, doc.audit_date)
	values = {"sample_n": sample, "sample_flag": 1 if min_sample and sample < min_sample else 0}
	if cint(doc.critical_failed):
		values["nc_status"] = SUGGESTED
	doc.db_set(values)
	feedback.after_submit(doc)


# --- quyền theo khoa (FR-M12-08.1) ------------------------------------------------------------------------------


def allowed_departments(user=None):
	"""None = mọi khoa; danh sách = chỉ các khoa có User Permission (R08/R12)."""
	user = user or frappe.session.user
	if user == "Administrator":
		return None
	roles = set(frappe.get_roles(user))
	if roles & WIDE_ROLES or not roles & DEPT_ROLES:
		return None
	return frappe.get_all("User Permission", filters={"user": user, "allow": "Department"}, pluck="for_value")


def query_conditions(user=None):
	departments = allowed_departments(user)
	if departments is None:
		return ""
	if not departments:
		return "1=0"
	values = ", ".join(frappe.db.escape(name) for name in departments)
	return f"`tab{DOCTYPE}`.`department` in ({values})"


def has_permission(doc, user=None, permission_type=None):
	departments = allowed_departments(user)
	if departments is None:
		return None
	return doc.department in departments
