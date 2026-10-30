"""Chứng chỉ nhân viên (FEAT-036, FR-M4-02, UC-19, BRU-HR-002).

Chứng chỉ có số, nơi cấp, ngày cấp, hạn (hoặc Không hết hạn) và file scan ≤ 10 MB. Gia hạn là một bản ghi mới trỏ về
bản cũ (``renews``): bản cũ thành Superseded và được giữ làm lịch sử. Việc hằng ngày đánh dấu hết hạn và nhắc nhân viên
cùng R02 ở mức 60/30/7 ngày (`tracecore.hr.reminders`). Kiểm tra năng lực trạm theo chứng chỉ là việc của FEAT-037;
`valid_certificate_types` là đầu vào của nó.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, today

from tracecore.core import audit, notification
from tracecore.hr import reminders

DOCTYPE = "Certificate"
VALID, EXPIRED, SUPERSEDED = "Valid", "Expired", "Superseded"
MAX_SCAN_BYTES = 10 * 1024 * 1024


def status_for(doc) -> str:
	if doc.no_expiry or not doc.expires_on:
		return VALID
	return EXPIRED if getdate(doc.expires_on) < getdate(today()) else VALID


def _check_scan(scan):
	if not scan:
		return
	size = frappe.db.get_value("File", {"file_url": scan}, "file_size")
	if size and size > MAX_SCAN_BYTES:
		frappe.throw(_("The scan file is larger than {0} MB.").format(MAX_SCAN_BYTES // (1024 * 1024)))


def _check_renewal(doc):
	if not doc.renews:
		return
	old = frappe.db.get_value(DOCTYPE, doc.renews, ["employee", "certificate_type", "status"], as_dict=True)
	if not old or (old.employee, old.certificate_type) != (doc.employee, doc.certificate_type):
		frappe.throw(_("A renewal must be for the same employee and certificate type."))


def validate_certificate(doc):
	if doc.no_expiry:
		doc.expires_on = None
	elif not doc.expires_on:
		frappe.throw(_("Expiry date is required unless the certificate does not expire."))
	if doc.expires_on and getdate(doc.expires_on) < getdate(doc.issued_on):
		frappe.throw(_("Expiry date cannot be before the issue date."))
	_check_scan(doc.scan)
	_check_renewal(doc)
	if doc.status != SUPERSEDED:
		doc.status = status_for(doc)


def supersede_renewed(doc):
	"""Bản gia hạn vừa tạo: bản cũ thành Superseded, giữ nguyên làm lịch sử (FR-M4-02.3)."""
	if not doc.renews:
		return
	frappe.db.set_value(DOCTYPE, doc.renews, "status", SUPERSEDED, update_modified=False)
	audit.log("Update", DOCTYPE, doc.renews, new={"event": "Certificate Superseded", "renewed_by": doc.name})


def valid_certificate_types(employee, on_date=None) -> set[str]:
	"""Loại chứng chỉ còn hiệu lực của `employee` vào `on_date` (mặc định hôm nay), đầu vào của FEAT-037."""
	on_date = getdate(on_date or today())
	rows = frappe.get_all(
		DOCTYPE,
		filters={"employee": employee, "status": ["!=", SUPERSEDED]},
		fields=["certificate_type", "no_expiry", "expires_on"],
	)
	return {
		row.certificate_type
		for row in rows
		if row.no_expiry or (row.expires_on and getdate(row.expires_on) >= on_date)
	}


def _employee_users(employee):
	user = frappe.db.get_value("Employee", employee, "user_id")
	return [user] if user else []


def run_daily():
	"""Hết hạn → Expired và báo một lần; sắp hết hạn → nhắc ở mức 60/30/7 (nhân viên và R02 qua Notification Rule)."""
	day = getdate(today())
	for row in frappe.get_all(
		DOCTYPE,
		filters={"status": VALID, "no_expiry": 0, "expires_on": ["is", "set"]},
		fields=[
			"name",
			"employee",
			"employee_name",
			"certificate_type",
			"certificate_no",
			"expires_on",
			"reminded_level",
		],
	):
		days_left = date_diff(row.expires_on, day)
		level = reminders.level_for(days_left)
		if not reminders.is_due(level, row.reminded_level):
			continue
		doc = frappe._dict(doctype=DOCTYPE, name=row.name)
		if level == reminders.EXPIRED:
			frappe.db.set_value(
				DOCTYPE, row.name, {"status": EXPIRED, "reminded_level": level}, update_modified=False
			)
			event = "CERTIFICATE_EXPIRED"
			subject = _("Certificate {0} of {1} has expired").format(row.certificate_no, row.employee_name)
		else:
			frappe.db.set_value(DOCTYPE, row.name, "reminded_level", level, update_modified=False)
			event = "CERTIFICATE_EXPIRING"
			subject = _("Certificate {0} of {1} expires in {2} days").format(
				row.certificate_no, row.employee_name, days_left
			)
		notification.emit(event, doc, subject, users=_employee_users(row.employee))
		if level == reminders.EXPIRED:
			# FR-M4-02.2: năng lực trạm yêu cầu chứng chỉ này bị tạm dừng; báo R02 và nhân viên
			from tracecore.hr import competency

			competency.notify_suspended(row.employee, row.certificate_type, row.certificate_no)
