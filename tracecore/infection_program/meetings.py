"""Biên bản họp Hội đồng KSNK (FEAT-058; FR-M11-08, FR-M11-08.1, FR-M11-08.2; UC-41 bước 6, A3; A-133 c).

- Ghi sổ biên bản → mỗi kết luận một ToDo của Frappe giao cho user của người chủ trì (không có user thì giao người
  ghi sổ kèm cảnh báo); kết luận đã có ToDo không tạo lại.
- Đóng ToDo → kết luận "Xong"; mở lại → "Mở". Hủy biên bản → hủy ToDo còn mở.
- ``open_resolutions``: kết luận chưa đóng của các lần họp trước (hiện khi mở biên bản mới và trên SCR-48).
"""

import frappe
from frappe import _
from frappe.utils import strip_html

from tracecore.infection_program import structure

DOCTYPE = "IC Committee Meeting"
CHILD = "IC Resolution"
OPEN, DONE = "Open", "Done"


def validate(doc):
	committee = structure.active_committee(doc.meeting_date)
	doc.committee = committee.name if committee else None
	seen = set()
	for row in doc.attendees:
		if row.employee in seen:
			frappe.throw(_("Employee {0} is listed more than once in attendees.").format(row.employee))
		seen.add(row.employee)


def _assignee(row):
	user = frappe.db.get_value("Employee", row.responsible, "user_id")
	if user and frappe.db.get_value("User", user, "enabled"):
		return user, False
	return frappe.session.user, True


def on_submit(doc):
	"""FR-M11-08.1: đúng một ToDo cho mỗi kết luận."""
	fallback = []
	for row in doc.resolutions:
		if row.todo and frappe.db.exists("ToDo", row.todo):
			continue
		user, is_fallback = _assignee(row)
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"status": "Open",
				"priority": "Medium",
				"allocated_to": user,
				"assigned_by": frappe.session.user,
				"date": row.due_date,
				"description": strip_html(row.content or ""),
				"reference_type": DOCTYPE,
				"reference_name": doc.name,
			}
		).insert(ignore_permissions=True)
		row.db_set("todo", todo.name, update_modified=False)
		if is_fallback:
			fallback.append(row.responsible_name or row.responsible)
	if fallback:
		frappe.msgprint(
			_("No user account for {0}; the follow-up task is assigned to you.").format(", ".join(fallback)),
			indicator="orange",
		)


def on_cancel(doc):
	for row in doc.resolutions:
		if row.todo and frappe.db.get_value("ToDo", row.todo, "status") == "Open":
			frappe.db.set_value("ToDo", row.todo, "status", "Cancelled")


def on_todo_update(todo, method=None):
	"""Hook ``ToDo.on_update``: đóng việc theo dõi → kết luận Xong (mở lại → Mở)."""
	if todo.reference_type != DOCTYPE:
		return
	row = frappe.db.get_value(CHILD, {"todo": todo.name, "parenttype": DOCTYPE}, ["name", "status"], as_dict=True)
	if not row:
		return
	status = DONE if todo.status == "Closed" else OPEN if todo.status == "Open" else row.status
	if status != row.status:
		frappe.db.set_value(CHILD, row.name, "status", status, update_modified=False)


def open_resolutions(exclude=None):
	"""Kết luận chưa đóng của các biên bản đã ghi sổ (mới nhất trước), trừ biên bản ``exclude``."""
	rows = frappe.db.sql(
		"""
		select r.name, r.parent as meeting, m.meeting_date, r.content, r.responsible, r.responsible_name,
			r.due_date, r.status, r.todo
		from `tabIC Resolution` r join `tabIC Committee Meeting` m on m.name = r.parent
		where r.parenttype = 'IC Committee Meeting' and m.docstatus = 1 and r.status = 'Open'
			and m.name != %(exclude)s
		order by m.meeting_date desc, r.idx asc
		""",
		{"exclude": exclude or ""},
		as_dict=True,
	)
	return rows


@frappe.whitelist(methods=["GET"])
def open_resolutions_for(meeting=None):
	"""Form ``IC Committee Meeting`` hiện danh sách kết luận mở của các lần họp trước (FR-M11-08.2)."""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("You are not allowed to read committee meetings."), frappe.PermissionError)
	return open_resolutions(exclude=meeting)
