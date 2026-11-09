"""Dữ liệu và thao tác của màn SCR-50 (mẫu phiếu & lịch) và SCR-53 (báo cáo tuân thủ) trên Page tc-ksnk (FEAT-060).

Quyền thật nằm ở DocPerm/`has_permission` (đọc/ghi qua ``frappe.get_list``/``doc.save`` theo người gọi). Lỗi nghiệp vụ
trả ``{"ok": false, "error": {title, reason, action}}`` để màn hiện alert-error inline (design.md), không modal.
"""

import functools

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, getdate, today

from tracecore.compliance_audit import compliance, nc, schedule, templates
from tracecore.core.errors import BlockedError

TEMPLATE_FIELDS = (
	"template_code",
	"title",
	"audit_type",
	"scoring_method",
	"bundle_type",
	"effective_from",
	"min_sample",
	"pass_threshold",
	"legal_ref",
)
ITEM_FIELDS = ("item_code", "section", "question", "answer_type", "options", "weight", "is_critical", "guidance")
SCHEDULE_FIELDS = ("audit_template", "frequency", "target_count", "assignee", "active")
SAVEPOINT = "tc_audit_board"


def _inline(fn):
	"""Lỗi quyền/nghiệp vụ của thao tác ghi → body ``ok: false`` (hoàn tác phần ghi dở) để màn báo inline."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		frappe.db.savepoint(SAVEPOINT)
		try:
			return fn(*args, **kwargs)
		except frappe.PermissionError as error:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.clear_last_message()
			return _error(_("Not permitted"), str(error), _("Ask R01 or R10 for access."))
		except BlockedError as error:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.clear_last_message()
			return {"ok": False, "error": error.block.as_dict()}
		except frappe.ValidationError as error:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.clear_last_message()
			return _error(_("Not saved"), frappe.utils.strip_html(str(error)), _("Correct the data, then save again."))

	return wrapper


def _error(title, reason, action):
	return {"ok": False, "error": {"title": title, "reason": reason, "action": action}}


def _options(doctype, field):
	return [value for value in (frappe.get_meta(doctype).get_field(field).options or "").split("\n") if value]


# --- SCR-50: mẫu phiếu --------------------------------------------------------------------------------------------


def _status(row, active):
	if row.docstatus == 0:
		return "Draft"
	if row.docstatus == 2:
		return "Cancelled"
	if active.get(row.template_code) == row.name:
		return "Approved"
	if getdate(row.effective_from) > getdate():
		return "Scheduled"
	return "Superseded"


def template_board(template=None):
	rows = frappe.get_list(
		templates.DOCTYPE,
		fields=["name", "template_code", "title", "version_no", "docstatus", "effective_from", "audit_type",
			"scoring_method"],
		order_by="template_code asc, version_no desc",
		limit_page_length=0,
	)
	active = {code: templates.active_version(code) for code in {row.template_code for row in rows}}
	for row in rows:
		row["status"] = _status(row, active)
	selected = template or next((row.name for row in rows if row.docstatus == 0), None)
	selected = selected or (rows[0].name if rows else None)
	return {
		"ok": True,
		"templates": rows,
		"selected": _detail(selected) if selected else None,
		"can_create": frappe.has_permission(templates.DOCTYPE, "create"),
		"options": {
			"audit_types": _options(templates.DOCTYPE, "audit_type"),
			"scoring_methods": _options(templates.DOCTYPE, "scoring_method"),
			"bundle_types": _options(templates.DOCTYPE, "bundle_type"),
			"answer_types": _options(templates.ITEM_DOCTYPE, "answer_type"),
		},
	}


def _detail(name):
	doc = frappe.get_doc(templates.DOCTYPE, name)
	doc.check_permission("read")
	active = templates.active_version(doc.template_code)
	data = {field: doc.get(field) for field in ("name", "version_no", "docstatus", "superseded_by", *TEMPLATE_FIELDS)}
	data["items"] = [{field: row.get(field) for field in ITEM_FIELDS} for row in doc.items]
	data["status"] = _status(doc, {doc.template_code: active})
	data["can_edit"] = doc.docstatus == 0 and doc.has_permission("write")
	data["can_approve"] = doc.docstatus == 0 and doc.has_permission("submit")
	data["can_revise"] = doc.docstatus == 1 and frappe.has_permission(templates.DOCTYPE, "create")
	return data


@_inline
def save_template(values):
	values = frappe._dict(values or {})
	if values.get("name"):
		doc = frappe.get_doc(templates.DOCTYPE, values.name)
		if doc.docstatus != 0:
			frappe.throw(
				_(
					"Version {0} is approved and locked. Create version V{1} to change it; audits already filled keep "
					"version {0}."
				).format(doc.name, cint(doc.version_no) + 1)
			)
	else:
		doc = frappe.new_doc(templates.DOCTYPE)
	doc.update({field: values.get(field) for field in TEMPLATE_FIELDS if field in values})
	doc.set("items", [{field: row.get(field) for field in ITEM_FIELDS} for row in values.get("items") or []])
	doc.save()
	return {"ok": True, "name": doc.name}


@_inline
def approve_template(name):
	doc = frappe.get_doc(templates.DOCTYPE, name)
	doc.submit()
	return {"ok": True, "name": doc.name}


@_inline
def new_version(name):
	return {"ok": True, "name": templates.new_version(name).name}


# --- SCR-50: lịch giám sát -----------------------------------------------------------------------------------------


def schedule_board(on=None):
	on = getdate(on or today())
	rows = frappe.get_list(
		schedule.DOCTYPE,
		filters={"active": 1},
		fields=["name", "template_code", "template_title", "frequency", "target_count", "assignee", "assignee_name"],
		order_by="name desc",
		limit_page_length=0,
	)
	for row in rows:
		row["coverage"] = schedule.coverage(row.name, on)
		target = sum(cell["target"] for cell in row["coverage"])
		done = sum(min(cell["done"], cell["target"]) for cell in row["coverage"])
		row["coverage_pct"] = round(done * 100 / target) if target else 0
		row["period"] = schedule.period_of(row.frequency, on)[2]
	return {"ok": True, "schedules": rows, "can_create": frappe.has_permission(schedule.DOCTYPE, "create")}


@_inline
def save_schedule(values):
	values = frappe._dict(values or {})
	doc = frappe.get_doc(schedule.DOCTYPE, values.name) if values.get("name") else frappe.new_doc(schedule.DOCTYPE)
	doc.update({field: values.get(field) for field in SCHEDULE_FIELDS if field in values})
	doc.set("departments", [{"department": row.get("department")} for row in values.get("departments") or []])
	doc.save()
	return {"ok": True, "name": doc.name}


# --- SCR-53: báo cáo tuân thủ và phản hồi khoa ------------------------------------------------------------------


def _feedback_share(names):
	if not names:
		return None
	sent = frappe.get_all(
		"Notification Delivery",
		filters={"event_code": "AUDIT_FEEDBACK", "ref_doctype": "Audit Session", "ref_name": ["in", names]},
		pluck="ref_name",
		distinct=True,
	)
	return round(len(set(sent)) * 100 / len(names))


def compliance_board(filters):
	filters = frappe._dict(filters or {})
	filters.from_date = getdate(filters.from_date or get_first_day(today()))
	filters.to_date = getdate(filters.to_date or today())
	rows = compliance.aggregate(filters)
	for row in rows:
		row["rate_label"] = compliance.rate_label(row)
	passed = sum(row.passed for row in rows)
	scored = sum(row.scored for row in rows)
	cards = {
		"posted": sum(row.sessions for row in rows),
		"passed": passed,
		"scored": scored,
		"pass_rate": flt(passed * 100 / scored, 1) if scored else None,
		"departments": len({row.department for row in rows}),
		"critical": sum(row.critical_failed for row in rows),
	}
	recent = []
	if frappe.has_permission("Audit Session", "read"):
		session_filters = {
			"docstatus": 1,
			"audit_date": ["between", [filters.from_date, filters.to_date]],
			**{field: filters[field] for field in ("audit_type", "template_code") if filters.get(field)},
		}
		recent = frappe.get_list(
			"Audit Session",
			filters=session_filters,
			fields=["name", "department", "template_title", "template_code", "audit_date", "score_pct", "result",
				"critical_failed", "nc_status", "nc_name"],
			order_by="audit_date desc, creation desc",
			limit_page_length=20,
		)
		cards["feedback_pct"] = _feedback_share([row.name for row in recent])
	can_decide = nc.can_decide()
	return {
		"ok": True,
		"filters": filters,
		"cards": cards,
		"rows": rows,
		"recent": recent,
		"pending": nc.pending() if can_decide else [],
		"can_decide": can_decide,
	}
