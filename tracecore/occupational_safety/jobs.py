"""Việc hằng ngày của M16 (FEAT-071; FR-M16-04, 04.1, 07, 08; NFR-PRIV-02; A-137 e, l).

- Mốc theo dõi chưa ghi ngày thực hiện: nhắc nhân viên + R11 một lần khi còn ≤ 3 ngày; quá hạn nhắc mỗi ngày, tối đa 7 lần.
- Tiêm chủng đến hạn (`immunization.remind_due`), tồn thuốc dự phòng (`pep_stock.check`).
- Hồ sơ đã đóng quá thời hạn lưu (`IC Program Settings.exposure_retention_months`) → xóa định danh, ghi Audit Log.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, date_diff, getdate, today

from tracecore.core import audit, notification
from tracecore.occupational_safety import exposure, immunization, pep_stock

PRE_REMINDER_DAYS = 3
MAX_OVERDUE_REMINDERS = 7
CHILD = "Exposure Follow-up"


def run_daily(day=None):
	day = getdate(day or today())
	remind_followups(day)
	immunization.remind_due(day)
	pep_stock.check(day)
	deidentify_expired(day)


def remind_followups(day=None):
	"""Trả số lần nhắc đã gửi."""
	day = getdate(day or today())
	sent = 0
	for name in frappe.get_all(exposure.DOCTYPE, filters={"status": "Following Up"}, pluck="name"):
		doc = frappe.get_doc(exposure.DOCTYPE, name)
		user = frappe.db.get_value("Employee", doc.employee, "user_id") if doc.employee else None
		for row in doc.followups:
			if row.done_on or not row.due_date:
				continue
			days_left = date_diff(row.due_date, day)
			if 0 <= days_left <= PRE_REMINDER_DAYS and not cint(row.pre_reminded):
				values = {"pre_reminded": 1}
			elif (
				days_left < 0
				and cint(row.reminder_count) < MAX_OVERDUE_REMINDERS
				and (not row.last_reminded_on or getdate(row.last_reminded_on) < day)
			):
				values = {"reminder_count": cint(row.reminder_count) + 1, "last_reminded_on": day}
			else:
				continue
			frappe.db.set_value(CHILD, row.name, values, update_modified=False)
			subject = (
				_("Exposure {0}: follow-up step {1} was due on {2}")
				if days_left < 0
				else _("Exposure {0}: follow-up step {1} is due on {2}")
			).format(doc.name, row.step, frappe.format(row.due_date, "Date"))
			notification.emit(
				"EXPOSURE_FOLLOWUP_DUE",
				doc,
				subject=subject,
				users=[user] if user else [],
				link=f"{exposure.LINK}?exposure={doc.name}",
			)
			sent += 1
	return sent


def deidentify_expired(day=None):
	"""NFR-PRIV-02: thời hạn trống → không làm gì; chỉ hồ sơ đã đóng (Completed/Cancelled)."""
	months = cint(frappe.db.get_single_value(exposure.SETTINGS, "exposure_retention_months"))
	if months <= 0:
		return 0
	cutoff = add_months(getdate(day or today()), -months)
	names = frappe.get_all(
		exposure.DOCTYPE,
		filters={
			"deidentified": 0,
			"status": ["in", ["Completed", "Cancelled"]],
			"occurred_at": ["<", cutoff],
		},
		pluck="name",
	)
	for name in names:
		exposure.deidentify(frappe.get_doc(exposure.DOCTYPE, name))
		audit.log(
			"Update",
			exposure.DOCTYPE,
			name,
			reason=_("Personal identifiers removed after the retention period"),
		)
	return len(names)
