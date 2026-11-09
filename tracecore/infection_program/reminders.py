"""Nhắc hạn của chương trình KSNK (FEAT-058; FR-M11-05, FR-M11-05.1, FR-M11-07, FR-M11-08; ADR-014; A-133).

Scheduler ``daily`` gọi ``run_daily``:

- hoạt động của kế hoạch năm đã duyệt và kết luận họp Hội đồng đã ghi sổ, chưa xong: còn ≤ 7 ngày tới hạn → nhắc
  "sắp tới hạn", quá hạn → nhắc "quá hạn"; mỗi mốc đúng một lần (cờ ẩn trên dòng), dừng khi Hoàn thành / Xong;
- văn bản nội bộ Hiệu lực còn ≤ 30 ngày tới hạn rà soát hoặc đã quá → "Cần rà soát" và báo R01 (BRU-ICP-005).

Người nhận: người chủ trì (user của Employee) do nơi gọi truyền + vai trò mặc định ``TC R01`` của Notification Rule.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, formatdate, getdate, today

from tracecore.core import notification

PLAN = "IC Annual Plan"
MEETING = "IC Committee Meeting"
DOCUMENT = "IC Procedure Document"
DUE_SOON_DAYS = 7
REVIEW_DAYS = 30
DONE_STATUSES = ("Completed", "Done")
SOURCES = (
	# (child DocType, parent DocType, sự kiện sắp tới hạn, sự kiện quá hạn, trường nội dung)
	("IC Plan Activity", PLAN, "IC_PLAN_ACTIVITY_DUE", "IC_PLAN_ACTIVITY_OVERDUE", "activity"),
	("IC Resolution", MEETING, "IC_RESOLUTION_DUE", "IC_RESOLUTION_OVERDUE", "content"),
)
EFFECTIVE, REVIEW_NEEDED, SUPERSEDED = "Effective", "Review Needed", "Superseded"


def display_status(status, due_date, on=None):
	"""completed / overdue / due_soon / in_progress / planned — "sắp tới hạn", "quá hạn" chỉ tính khi hiển thị."""
	if status in DONE_STATUSES:
		return "completed"
	if due_date:
		days = date_diff(getdate(due_date), getdate(on or today()))
		if days < 0:
			return "overdue"
		if days <= DUE_SOON_DAYS:
			return "due_soon"
	return "in_progress" if status == "In Progress" else "planned"


def _user_of(employee):
	return frappe.db.get_value("Employee", employee, "user_id") if employee else None


def _open_rows(child, parent, field):
	return frappe.db.sql(
		f"""
		select c.name, c.parent, c.due_date, c.status, c.responsible, c.reminded_due_soon, c.reminded_overdue,
			c.`{field}` as label
		from `tab{child}` c
		join `tab{parent}` p on p.name = c.parent
		where c.parenttype = %(parent)s and p.docstatus = 1 and c.due_date is not null
			and c.status not in %(done)s
		""",
		{"parent": parent, "done": DONE_STATUSES},
		as_dict=True,
	)


def _remind_rows(on):
	sent = 0
	for child, parent, due_event, overdue_event, field in SOURCES:
		for row in _open_rows(child, parent, field):
			days = date_diff(getdate(row.due_date), on)
			if days < 0 and not row.reminded_overdue:
				event, flag = overdue_event, "reminded_overdue"
				subject = _("Overdue since {0}: {1}").format(formatdate(row.due_date, "dd/mm/yyyy"), row.label)
			elif 0 <= days <= DUE_SOON_DAYS and not row.reminded_due_soon:
				event, flag = due_event, "reminded_due_soon"
				subject = _("Due on {0}: {1}").format(formatdate(row.due_date, "dd/mm/yyyy"), row.label)
			else:
				continue
			doc = frappe.get_doc(parent, row.parent)
			notification.emit(
				event, doc=doc, subject=subject, message=row.label, users=[_user_of(row.responsible)]
			)
			frappe.db.set_value(child, row.name, flag, 1, update_modified=False)
			sent += 1
	return sent


def review_needed(review_due, on=None):
	return bool(review_due) and date_diff(getdate(review_due), getdate(on or today())) <= REVIEW_DAYS


def _flag_documents(on):
	flagged = 0
	for name in frappe.get_all(DOCUMENT, filters={"status": EFFECTIVE}, pluck="name"):
		doc = frappe.get_doc(DOCUMENT, name)
		if not review_needed(doc.review_due, on):
			continue
		doc.status = REVIEW_NEEDED
		doc.flags.ignore_permissions = True
		doc.flags.keep_status = True
		doc.save()
		notification.emit(
			"IC_DOCUMENT_REVIEW_DUE",
			doc=doc,
			subject=_("Review due on {0}: {1} {2}").format(
				formatdate(doc.review_due, "dd/mm/yyyy"), doc.doc_code, doc.title
			),
			message=doc.title,
		)
		flagged += 1
	return flagged


def run_daily(on=None):
	"""Scheduler hằng ngày (hooks ``scheduler_events.daily``)."""
	on = getdate(on or today())
	return {"rows": _remind_rows(on), "documents": _flag_documents(on)}


def attention_count(on=None):
	"""Số việc chờ của màn SCR-48: hoạt động quá hạn (kế hoạch đã duyệt năm nay) + văn bản cần rà soát."""
	on = getdate(on or today())
	overdue = frappe.db.sql(
		"""
		select count(*) from `tabIC Plan Activity` c join `tabIC Annual Plan` p on p.name = c.parent
		where c.parenttype = 'IC Annual Plan' and p.docstatus = 1 and p.year = %(year)s
			and c.status != 'Completed' and c.due_date < %(on)s
		""",
		{"year": on.year, "on": on},
	)[0][0]
	documents = frappe.db.count(DOCUMENT, {"status": REVIEW_NEEDED})
	return int(overdue or 0) + int(documents or 0)
