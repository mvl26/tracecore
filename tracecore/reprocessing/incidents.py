"""Sự cố / NC / CAPA (M2, FEAT-030, UC-15, FR-M2-21, FR-M2-22, WF-06).

Vòng đời ``Incident CAPA``: người phát hiện (hoặc hệ thống) tạo ở New → R01/R02 phân tích (Analysis) → lập CAPA có nguyên
nhân gốc và hành động (CAPA) → người phụ trách hoàn thành từng hành động → R01/R02 chuyển kiểm tra hiệu quả
(Verification) → đóng (Closed, ghi sổ). R01/R02 hủy được khi còn mở, bắt buộc lý do (Cancelled, ghi sổ).

Chỉ dịch vụ này đổi trạng thái và các trường của quyết định (cờ ``flags.tc_incident``); sửa tay trên form bị chặn.
NC tự tạo qua hook của lô rửa / mẻ / kiểm đếm T3, idempotent theo chứng từ nguồn và loại. Thông báo là chuông Desk
(Notification Log) như FEAT-032; email/SMS thuộc FEAT-010.
"""

import frappe
from frappe import _
from frappe.utils import cstr, getdate, now_datetime, today

from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Incident CAPA"
ACTION_DOCTYPE = "CAPA Action"
FLAG = "tc_incident"
R01, R02 = "TC R01", "TC R02"
SUPERVISOR_ROLES = (R01, R02)
LINK_FIELDS = (
	"set_unit",
	"pack",
	"assembly_record",
	"wash_batch",
	"sterilization_load",
	"equipment",
	"employee",
)
# Trường chỉ dịch vụ được đổi; sửa tay trên form bị chặn
PROTECTED = (
	"status",
	"occurred_at",
	"reported_by",
	"is_auto",
	"source_doctype",
	"source_name",
	"verification_result",
	"closed_by",
	"closed_at",
	"cancel_reason",
)
ACTION_PROTECTED = ("status", "result", "done_at", "last_reminded_on")
OPEN = ("New", "Analysis", "CAPA", "Verification")
NC_TYPES = {"Shortage": "Missing Instrument", "Foreign Instrument": "Foreign Instrument"}


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _is_supervisor(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(SUPERVISOR_ROLES))


def _require_supervisor():
	if not _is_supervisor():
		raise _blocked(
			"INCIDENT_NOT_ALLOWED",
			_("Not allowed"),
			_("Only R01 or R02 can move, close or cancel an incident."),
			_("Ask R01 or R02 to do this step."),
		)


def _users_with(role):
	holders = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	if not holders:
		return []
	return frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name")


def _notify(users, subject, doc):
	"""Thông báo chuông Desk (Notification Log); email/SMS và SCR-42 thuộc FEAT-010."""
	for user in dict.fromkeys(users):
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"from_user": frappe.session.user,
				"type": "Alert",
				"subject": subject,
				"document_type": DOCTYPE,
				"document_name": doc.name,
			}
		).insert(ignore_permissions=True)


# --- Tạo ----------------------------------------------------------------------------------------------


def create(values, auto=False):
	"""Tạo Incident ở trạng thái New (FR-M2-21); `values` gồm loại, mức, mô tả, ảnh và các liên kết đối tượng."""
	doc = frappe.get_doc({"doctype": DOCTYPE, **(values or {})})
	doc.flags[FLAG] = True
	doc.is_auto = 1 if auto else 0
	doc.insert(ignore_permissions=True)
	return doc


def validate(doc):
	"""Luật của một Incident; gọi từ ``IncidentCAPA.validate``."""
	if doc.is_new():
		doc.status = "New"
		doc.occurred_at = doc.occurred_at or now_datetime()
		doc.reported_by = frappe.session.user
		if not doc.flags.get(FLAG):
			doc.is_auto = 0
			doc.source_doctype = doc.source_name = None
	else:
		_guard_changes(doc)
	doc.description = cstr(doc.description).strip()
	if not any(doc.get(field) for field in LINK_FIELDS):
		raise _blocked(
			"INCIDENT_LINK_REQUIRED",
			_("Linked object is required"),
			_(
				"The incident is not linked to any load, equipment, set, pack, employee, wash batch or assembly."
			),
			_("Choose at least one linked object, then save."),
		)


def _guard_changes(doc):
	if doc.flags.get(FLAG):
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [field for field in PROTECTED if cstr(doc.get(field)) != cstr(before.get(field))]
	old_actions = {row.name: row for row in before.get("actions") or []}
	for row in doc.get("actions") or []:
		old = old_actions.get(row.name)
		for field in ACTION_PROTECTED:
			if cstr(row.get(field)) != cstr(
				old.get(field) if old else row.meta.get_field(field).default or ""
			):
				changed.append(f"actions.{field}")
	if changed:
		frappe.throw(
			_("These fields change only through the incident actions: {0}").format(", ".join(changed)),
			frappe.ValidationError,
		)


def after_insert(doc):
	"""Thông báo R02; mức High thêm R01 (FR-M2-21, FR-M2-21.3)."""
	users = _users_with(R02)
	if doc.severity == "High":
		users = _users_with(R01) + users
	subject = _("New incident {0}: {1}").format(doc.name, _(doc.incident_type))
	_notify(users, subject, doc)


def guard_submit(doc):
	if not doc.flags.get(FLAG) or doc.status not in ("Closed", "Cancelled"):
		frappe.throw(_("Close or cancel the incident with its actions, not by submitting it."))


def guard_cancel(doc):
	frappe.throw(_("A closed incident cannot be cancelled. Create a new incident instead."))


# --- Chuyển trạng thái (WF-06) --------------------------------------------------------------------------


def _open(name, *statuses):
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	if doc.docstatus != 0 or (statuses and doc.status not in statuses):
		raise _blocked(
			"INCIDENT_STATUS_INVALID",
			_("Step not available"),
			_("Incident {0} is {1}.").format(doc.name, _(doc.status)),
			_("Reload the incident and use the step shown for its current status."),
		)
	return doc


def _save(doc, submit=False):
	doc.flags[FLAG] = True
	doc.flags.ignore_permissions = True
	if submit:
		doc.submit()
	else:
		doc.save()
	return doc


def start_analysis(name):
	"""New → Analysis (R01/R02)."""
	_require_supervisor()
	doc = _open(name, "New")
	doc.status = "Analysis"
	return _save(doc)


def plan_capa(name, root_cause=None, actions=None):
	"""Analysis → CAPA: cần nguyên nhân gốc và ≥ 1 hành động đủ mô tả, người phụ trách, hạn (FR-M2-22)."""
	_require_supervisor()
	doc = _open(name, "Analysis")
	if root_cause is not None:
		doc.root_cause = cstr(root_cause).strip()
	if actions is not None:
		doc.set("actions", [])
		for row in actions:
			doc.append(
				"actions",
				{
					"action_type": row.get("action_type") or "Corrective",
					"description": cstr(row.get("description")).strip(),
					"responsible": row.get("responsible"),
					"due_date": row.get("due_date"),
				},
			)
	if not cstr(doc.root_cause).strip():
		raise _blocked(
			"ROOT_CAUSE_REQUIRED",
			_("Root cause is required"),
			_("No root cause was entered."),
			_("Enter the root cause before planning actions."),
		)
	if not doc.get("actions"):
		raise _blocked(
			"CAPA_ACTION_REQUIRED",
			_("Action is required"),
			_("The incident has no corrective or preventive action."),
			_("Add at least one action with a responsible person and a due date."),
		)
	if any(not (row.description and row.responsible and row.due_date) for row in doc.actions):
		raise _blocked(
			"CAPA_ACTION_INCOMPLETE",
			_("Action is incomplete"),
			_("Every action needs a description, a responsible person and a due date."),
			_("Complete each action row, then try again."),
		)
	doc.status = "CAPA"
	return _save(doc)


def complete_action(name, row_name, result):
	"""Người phụ trách (hoặc R01/R02) ghi kết quả và đánh dấu Done một hành động (UC-15 bước 4)."""
	doc = _open(name, "CAPA")
	row = next((row for row in doc.actions if row.name == row_name), None)
	if not row:
		frappe.throw(
			_("Action {0} is not part of incident {1}.").format(row_name, name), frappe.DoesNotExistError
		)
	if frappe.session.user != row.responsible and not _is_supervisor():
		raise _blocked(
			"INCIDENT_NOT_ALLOWED",
			_("Not allowed"),
			_("Only the responsible person, R01 or R02 can complete this action."),
			_("Ask {0} to record the result.").format(row.responsible),
		)
	result = cstr(result).strip()
	if not result:
		raise _blocked(
			"RESULT_REQUIRED",
			_("Result is required"),
			_("No result was entered for the action."),
			_("Describe what was done, then mark it done."),
		)
	row.update({"status": "Done", "result": result, "done_at": now_datetime()})
	return _save(doc)


def submit_verification(name):
	"""CAPA → Verification: mọi hành động đã Done (UC-15 bước 5)."""
	_require_supervisor()
	doc = _open(name, "CAPA")
	if any(row.status != "Done" for row in doc.actions):
		raise _blocked(
			"CAPA_ACTIONS_OPEN",
			_("Actions are still open"),
			_("Not every corrective or preventive action is done."),
			_("Wait until each responsible person records the result."),
		)
	doc.status = "Verification"
	return _save(doc)


def close(name, verification_result):
	"""Verification → Closed (ghi sổ): chỉ R01/R02, cần kết quả kiểm tra hiệu quả (FR-M2-22.2, UC-15 E3)."""
	_require_supervisor()
	doc = _open(name, "Verification")
	verification_result = cstr(verification_result).strip()
	if not verification_result:
		raise _blocked(
			"VERIFICATION_REQUIRED",
			_("Effectiveness check is required"),
			_("No effectiveness check result was entered."),
			_("Describe how the actions were checked, then close the incident."),
		)
	doc.update(
		{
			"status": "Closed",
			"verification_result": verification_result,
			"closed_by": frappe.session.user,
			"closed_at": now_datetime(),
		}
	)
	return _save(doc, submit=True)


def cancel(name, reason):
	"""Hủy Incident còn mở (ghi sổ trạng thái Cancelled): chỉ R01/R02, bắt buộc lý do (FR-M2-21.4)."""
	_require_supervisor()
	doc = _open(name, *OPEN)
	reason = cstr(reason).strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for cancelling the incident."),
			_("Enter why the incident is cancelled."),
		)
	doc.update(
		{
			"status": "Cancelled",
			"cancel_reason": reason,
			"closed_by": frappe.session.user,
			"closed_at": now_datetime(),
		}
	)
	doc.flags.tc_audit_reason = reason
	return _save(doc, submit=True)


# --- NC tự tạo (FR-M2-21.1) -----------------------------------------------------------------------------


def _auto(source_doctype, source_name, incident_type, severity, description, links):
	"""Incident tự tạo, idempotent theo (chứng từ nguồn, loại); trả tên Incident."""
	existing = frappe.db.get_value(
		DOCTYPE,
		{"source_doctype": source_doctype, "source_name": source_name, "incident_type": incident_type},
		"name",
	)
	if existing:
		return existing
	values = {
		"incident_type": incident_type,
		"severity": severity,
		"description": description,
		"source_doctype": source_doctype,
		"source_name": source_name,
		**{key: value for key, value in links.items() if value},
	}
	return create(values, auto=True).name


def on_wash_failed(ctx):
	"""Hook ``tracecore_after_wash_failed``: lô rửa Không đạt → NC Wash Failed (FR-M2-04.4)."""
	sets = ", ".join(ctx.get("sets") or [])
	return _auto(
		"Wash Batch",
		ctx["batch"],
		"Wash Failed",
		"Medium",
		_("Wash batch {0} failed. Sets sent back to washing: {1}.").format(ctx["batch"], sets or "-"),
		{"wash_batch": ctx["batch"], "equipment": ctx.get("equipment")},
	)


def on_load_failed(ctx):
	"""Hook ``tracecore_after_load_failed``: mẻ Không đạt → NC Load Failed mức High (FR-M2-12.2)."""
	return _auto(
		"Sterilization Load",
		ctx["load"],
		"Load Failed",
		"High",
		_("Sterilization load {0} failed. Sets restart from {1}.").format(
			ctx["load"], ctx.get("redo_from") or "T4"
		),
		{"sterilization_load": ctx["load"], "equipment": ctx.get("equipment")},
	)


def on_assembly_nc(ctx):
	"""Hook ``tracecore_assembly_nc``: T3 thiếu dụng cụ / dụng cụ lạ → NC (FR-M2-06.2, FR-M1-02.4, A-35 T6)."""
	incident_type = NC_TYPES.get(ctx.get("kind"), "Other")
	items = ", ".join(ctx.get("items") or [])
	if incident_type == "Missing Instrument":
		text = _("Assembly {0} of set {1} is missing: {2}.")
	else:
		text = _("Assembly {0} of set {1} found an instrument outside the BOM: {2}.")
	return _auto(
		"Assembly Record",
		ctx["assembly"],
		incident_type,
		"Medium",
		text.format(ctx["assembly"], ctx.get("set_unit"), items or "-"),
		{"assembly_record": ctx["assembly"], "set_unit": ctx.get("set_unit")},
	)


def on_loaner_returned(ctx):
	"""Hook ``tracecore_loaner_returned``: trả bộ mượn thiếu dụng cụ → NC Missing Instrument (UC-04 E3, A-38 e)."""
	items = ", ".join(f"{line['name']} ({line['qty']})" for line in ctx.get("missing") or [])
	return _auto(
		"Loaner Set",
		ctx["loaner"],
		"Missing Instrument",
		"Medium",
		_("Loaner set {0} ({1}) was returned to the vendor missing: {2}.").format(
			ctx["loaner"], ctx.get("set_unit"), items or "-"
		),
		{"set_unit": ctx.get("set_unit")},
	)


# --- Nhắc quá hạn (FR-M2-22.1) --------------------------------------------------------------------------


def remind_overdue():
	"""Job hằng ngày: hành động chưa Done quá hạn → nhắc người phụ trách và R02, tối đa một lần/ngày; trả số lần nhắc."""
	rows = frappe.get_all(
		ACTION_DOCTYPE,
		filters={
			"parenttype": DOCTYPE,
			"status": "Open",
			"due_date": ["<", today()],
		},
		fields=["name", "parent", "responsible", "description", "due_date", "last_reminded_on"],
	)
	count = 0
	r02 = _users_with(R02)
	for row in rows:
		if row.last_reminded_on and getdate(row.last_reminded_on) >= getdate(today()):
			continue
		doc = frappe.get_doc(DOCTYPE, row.parent)
		if doc.docstatus != 0 or doc.status != "CAPA":
			continue
		subject = _("Overdue CAPA action in {0}: {1}").format(doc.name, row.description)
		_notify(([row.responsible] if row.responsible else []) + r02, subject, doc)
		frappe.db.set_value(ACTION_DOCTYPE, row.name, "last_reminded_on", today(), update_modified=False)
		count += 1
	return count
