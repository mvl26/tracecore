"""RPC tracecore.v1.ksnk_plan.* — màn SCR-48 Kế hoạch KSNK năm, văn bản nội bộ, họp Hội đồng (FEAT-058; UC-41; D7).

- ``status`` (GET, chỉ đọc): kế hoạch của năm (đã duyệt, không có thì bản Nháp mới nhất), chỉ số kèm giá trị gần nhất
  từ ``IC Indicator Value``, hoạt động có trạng thái hiển thị, sổ văn bản, họp gần nhất, kết luận mở, quyền người gọi.
- ``approve_plan`` (POST, R13): ghi sổ = phê duyệt (BRU-ICP-004).
- ``make_amendment`` (POST, R01): lập bản sửa đổi Nháp khi bản gốc còn hiệu lực (A-133 Q1).
- ``update_activity`` (POST, người chủ trì hoặc R01): trạng thái, minh chứng của hoạt động (A-133 Q2).

Lỗi nghiệp vụ trả ``{ok: false, error: {title, reason, action}}`` để màn hiện ``alert-error`` inline (design.md §6).
RPC Desk, không phải trạm/PDA nên không dùng ``@idempotent`` (như ``ksnk_structure``).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, strip_html, today

from tracecore.infection_program import annual_plan, meetings, reminders
from tracecore.ui import ksnk

PLAN = annual_plan.DOCTYPE
DOCUMENT = "IC Procedure Document"
MEETING = meetings.DOCTYPE
SCREEN_SLUG = annual_plan.SCREEN_SLUG
STATUS_LABEL = {
	"completed": "Completed",
	"overdue": "Overdue",
	"due_soon": "Due soon",
	"in_progress": "In Progress",
	"planned": "Planned",
}
DOC_STATUS_KEY = {"Effective": "effective", "Review Needed": "review", "Superseded": "superseded"}
DOCUMENT_LIMIT = 50


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == SCREEN_SLUG)
	if not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(_("You are not allowed to open the annual plan screen."), frappe.PermissionError)


def _block(title, error, action):
	frappe.clear_messages()
	return {
		"ok": False,
		"error": {"title": title, "reason": strip_html(str(error)) or title, "action": action},
	}


def _pick_plan(year):
	for docstatus in (1, 0):
		rows = frappe.get_list(
			PLAN,
			filters={"year": year, "docstatus": docstatus},
			pluck="name",
			order_by="creation desc",
			limit_page_length=1,
		)
		if rows:
			return rows[0]
	return None


def _row_status(status, due_date):
	key = reminders.display_status(status, due_date)
	return {"key": key, "label": _(STATUS_LABEL[key], context="IC Plan")}


def _plan_block(name):
	if not name:
		return None
	doc = frappe.get_doc(PLAN, name)
	summary = annual_plan.year_summary(name)
	creator = frappe.db.get_value("User", doc.owner, "full_name") or doc.owner
	activities = []
	for row in doc.activities:
		status = _row_status(row.status, row.due_date)
		activities.append(
			{
				"name": row.name,
				"activity": row.activity,
				"measure_group": _(row.measure_group) if row.measure_group else "",
				"responsible": row.responsible_name or row.responsible,
				"department": row.department_name or row.department or "",
				"due_date": str(row.due_date) if row.due_date else None,
				"budget_vnd": flt(row.budget_vnd),
				"status": row.status,
				"display_status": status["key"],
				"status_label": status["label"],
				"evidence": row.evidence or "",
				"can_update": doc.docstatus == 1 and annual_plan.can_update_activity(row),
			}
		)
	pending = frappe.get_all(PLAN, filters={"amended_from": name, "docstatus": 0}, pluck="name")
	return {
		"name": doc.name,
		"year": cint(doc.year),
		"docstatus": doc.docstatus,
		"amended_from": doc.amended_from,
		"objectives": doc.objectives or "",
		"created_by": creator,
		"approved_by": summary["approved_by"],
		"approved_on": str(doc.approved_on) if doc.approved_on else None,
		"total_budget_vnd": flt(doc.total_budget_vnd),
		"activities_total": summary["activities_total"],
		"activities_completed": summary["activities_completed"],
		"overdue": sum(1 for row in activities if row["display_status"] == "overdue"),
		"indicators": summary["indicators"],
		"activities": activities,
		"pending_amendment": pending[0] if pending else None,
		"provisional": summary["provisional"],
	}


def _documents():
	rows = frappe.get_list(
		DOCUMENT,
		filters={"status": ["!=", "Superseded"]},
		fields=["name", "doc_code", "title", "version_no", "review_due", "status"],
		order_by="review_due asc",
		limit_page_length=DOCUMENT_LIMIT,
	)
	on = getdate(today())
	result = []
	for row in rows:
		days = (getdate(row.review_due) - on).days if row.review_due else None
		result.append(
			{
				"name": row.name,
				"doc_code": row.doc_code,
				"title": row.title,
				"version_no": cint(row.version_no),
				"review_due": str(row.review_due) if row.review_due else None,
				"status": row.status,
				"status_key": "overdue"
				if days is not None and days < 0
				else DOC_STATUS_KEY.get(row.status, "effective"),
				"days_left": days,
			}
		)
	return result


def _meeting_block():
	rows = frappe.get_list(
		MEETING,
		filters={"docstatus": 1},
		fields=["name", "meeting_date"],
		order_by="meeting_date desc, creation desc",
		limit_page_length=1,
	)
	if not rows:
		return None
	doc = frappe.get_doc(MEETING, rows[0].name)
	return {
		"name": doc.name,
		"meeting_date": str(doc.meeting_date),
		"resolutions": [_resolution(row) for row in doc.resolutions],
	}


def _resolution(row):
	# kết luận mở mà chưa tới mốc nhắc hiện "Đang làm" như ảnh SCR-48
	status = _row_status(row.status if row.status == meetings.DONE else "In Progress", row.due_date)
	return {
		"content": row.content,
		"responsible": row.responsible_name or row.responsible,
		"due_date": str(row.due_date) if row.due_date else None,
		"status": row.status,
		"display_status": status["key"],
		"status_label": _("Done", context="IC Plan") if row.status == meetings.DONE else status["label"],
	}


def _status(year=None):
	year = cint(year) or getdate(today()).year
	roles = set(frappe.get_roles())
	plan = _plan_block(_pick_plan(year))
	documents = _documents() if frappe.has_permission(DOCUMENT, "read") else []
	meeting = _meeting_block() if frappe.has_permission(MEETING, "read") else None
	open_rows = meetings.open_resolutions(exclude=meeting["name"] if meeting else None) if meeting else []
	return {
		"year": year,
		"plan": plan,
		"documents": documents,
		"documents_attention": sum(1 for row in documents if row["status_key"] in ("review", "overdue")),
		"meeting": meeting,
		"open_resolutions": [
			{
				"meeting": row.meeting,
				"content": row.content,
				"responsible": row.responsible_name or row.responsible,
				"due_date": str(row.due_date) if row.due_date else None,
			}
			for row in open_rows
		],
		"can_approve": bool(plan and plan["docstatus"] == 0 and annual_plan.APPROVER_ROLE in roles),
		"can_amend": bool(
			plan
			and plan["docstatus"] == 1
			and frappe.has_permission(PLAN, "amend")
			and annual_plan.EDITOR_ROLE in roles
		),
		"can_create_plan": bool(not plan and frappe.has_permission(PLAN, "create")),
		"can_record_meeting": bool(frappe.has_permission(MEETING, "create")),
		# thao tác mở form theo quyền thật (DocPerm): màn luôn có lối mở/sửa/tạo mới bản ghi đang xem
		"can_write_plan": bool(plan and frappe.has_permission(PLAN, "write")),
		"can_write_document": bool(frappe.has_permission(DOCUMENT, "write")),
		"can_create_document": bool(frappe.has_permission(DOCUMENT, "create")),
		"can_write_meeting": bool(meeting and frappe.has_permission(MEETING, "write")),
	}


@frappe.whitelist(methods=["GET"])
def status(year=None):
	"""Dữ liệu màn SCR-48 cho năm ``year`` (mặc định năm nay)."""
	_require_screen()
	return _status(year)


def _run(savepoint, fn, title, action):
	frappe.db.savepoint(savepoint)
	try:
		return fn()
	except frappe.PermissionError:
		frappe.db.rollback(save_point=savepoint)
		raise
	except frappe.ValidationError as error:
		frappe.db.rollback(save_point=savepoint)
		return _block(title, error, action)


@frappe.whitelist(methods=["POST"])
def approve_plan(name):
	"""R13 ghi sổ kế hoạch Nháp (UC-41 bước 2; E1: người khác bị từ chối)."""
	_require_screen()

	def run():
		doc = annual_plan.approve(name)
		return {"ok": True, "name": doc.name, "status": _status(doc.year)}

	return _run(
		"ksnk_plan_approve",
		run,
		_("Plan not approved"),
		_("Open the plan, correct it and approve again."),
	)


@frappe.whitelist(methods=["POST"])
def make_amendment(name):
	"""R01 lập bản sửa đổi (UC-41 A1); trả tên bản Nháp để mở form."""
	_require_screen()

	def run():
		return {"ok": True, "name": annual_plan.make_amendment(name)}

	return _run(
		"ksnk_plan_amend",
		run,
		_("Amendment not created"),
		_("Finish or remove the pending draft of this year first."),
	)


@frappe.whitelist(methods=["POST"])
def update_activity(plan, row, status, evidence=None):
	"""Người chủ trì hoặc R01 cập nhật tiến độ một hoạt động (UC-41 bước 4)."""

	def run():
		doc = annual_plan.update_activity(plan, row, status, evidence)
		return {"ok": True, "name": doc.name}

	return _run(
		"ksnk_plan_activity",
		run,
		_("Progress not saved"),
		_("Check the status and evidence, then save again."),
	)
