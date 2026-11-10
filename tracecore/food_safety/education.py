"""Buổi truyền thông KSNK (FEAT-073; FR-M17-05, FR-M17-05.1, FR-M17-01.2; UC-56 bước 5; A-151 Q4).

- ``IC Education Session``: ngày, khoa, đối tượng (Người bệnh / Người nhà / Nhân viên / Người chế biến / Sinh viên), chủ
  đề theo nhóm biện pháp, số người, tài liệu truyền thông (Link `IC Procedure Document` loại Tài liệu truyền thông).
- R12 chỉ ghi và thấy buổi của khoa mình (User Permission Department, NFR-SEC-09); bản ghi không xóa (Audit Log).
- Tổng hợp quý theo đối tượng - chủ đề cho SCR-65 và Script Report.
"""

import frappe
from frappe import _
from frappe.utils import cint, formatdate, getdate, today

from tracecore.core.errors import Block, BlockedError

DOCTYPE = "IC Education Session"
MATERIAL_DOCTYPE = "IC Procedure Document"
MATERIAL_TYPE = "Communication Material"
WIDE_ROLES = frozenset({"TC R01", "TC R10", "TC R11", "TC R13", "System Manager"})
DEPT_ROLES = frozenset({"TC R12"})


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def validate(doc):
	"""Gọi từ ``ICEducationSession.validate``."""
	if cint(doc.attendee_count) < 1:
		raise _blocked(
			"EDUCATION_COUNT_INVALID",
			_("Number of attendees is required"),
			_("An education session needs at least one attendee."),
			_("Enter how many people attended."),
		)
	doc.session_date = getdate(doc.session_date or today())
	if doc.session_date > getdate(today()):
		raise _blocked(
			"EDUCATION_DATE_INVALID",
			_("Session date in the future"),
			_("Session date {0} is after today.").format(formatdate(doc.session_date)),
			_("Record the session after it has taken place."),
		)
	if doc.materials and frappe.db.get_value(MATERIAL_DOCTYPE, doc.materials, "doc_type") != MATERIAL_TYPE:
		raise _blocked(
			"EDUCATION_MATERIAL_INVALID",
			_("Not a communication material"),
			_("Document {0} is not a communication material for patients and families.").format(
				doc.materials
			),
			_("Choose a document of type Communication Material, or leave the field empty."),
		)


# --- phạm vi khoa (FR-M17-01.2, NFR-SEC-09) -----------------------------------------------------------------------


def allowed_departments(user=None):
	"""None = mọi khoa; danh sách = chỉ khoa có User Permission (R12)."""
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


# --- tổng hợp quý (FR-M17-05, .1) ---------------------------------------------------------------------------------


def quarter_of(day=None):
	day = getdate(day or today())
	return day.year, (day.month - 1) // 3 + 1


def quarter_bounds(year, quarter):
	year, quarter = cint(year), cint(quarter)
	start = getdate(f"{year}-{(quarter - 1) * 3 + 1:02d}-01")
	end_month = quarter * 3
	end = getdate(f"{year + 1}-01-01" if end_month == 12 else f"{year}-{end_month + 1:02d}-01")
	return start, frappe.utils.add_days(end, -1)


def quarter_summary(year, quarter, department=None):
	"""{label, sessions, attendees, rows[{audience, topic, sessions, attendees}]} của quý."""
	start, end = quarter_bounds(year, quarter)
	filters = {"session_date": ["between", [start, end]]}
	if department:
		filters["department"] = department
	rows = frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=["audience", "topic", "count(name) as sessions", "sum(attendee_count) as attendees"],
		group_by="audience, topic",
		order_by="audience asc, topic asc",
	)
	rows = [
		{
			"audience": row.audience,
			"topic": row.topic,
			"sessions": cint(row.sessions),
			"attendees": cint(row.attendees),
		}
		for row in rows
	]
	return {
		"label": f"Q{cint(quarter)}/{cint(year)}",
		"sessions": sum(row["sessions"] for row in rows),
		"attendees": sum(row["attendees"] for row in rows),
		"rows": rows,
	}
