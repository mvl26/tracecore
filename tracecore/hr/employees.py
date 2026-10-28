"""Hồ sơ nhân viên (FEAT-036, FR-M4-01, BRU-ID-006): mã NV- do hệ thống cấp, thẻ mặc định, nhắc khám sức khỏe/tiêm chủng.

Employee là HRMS Employee + Custom Field `tc_*`; nhân viên mới đặt tên theo series ``NV-`` (Property Setter) nên mã NV-
chính là tên bản ghi, được ghi vào `Code Registry` để in thẻ QR (nhãn "Employee Card") và quét ở trạm.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, today

from tracecore.core import code_registry, notification
from tracecore.hr import reminders

CODE_PREFIX = "NV"
# (trường ngày hạn, trường mức đã nhắc, tên hiển thị trong thông báo)
HEALTH_FIELDS = (
	("tc_health_check_expiry", "tc_health_remind_level", "Health check"),
	("tc_vaccination_expiry", "tc_vaccination_remind_level", "Vaccination"),
)


def register_code(doc):
	"""Ghi mã NV- của nhân viên vào sổ mã (một lần); tên không phải NV- (nhân viên cũ HR-EMP-) thì bỏ qua."""
	if doc.name.startswith(CODE_PREFIX + "-") and not code_registry.is_issued(doc.name):
		code_registry.register(doc.name, CODE_PREFIX, "Employee", doc.name)


def after_insert(doc, method=None):
	register_code(doc)
	if not doc.tc_card_id:
		# thẻ in từ mã NV- dùng được ngay làm thẻ đăng nhập; thẻ có sẵn của bệnh viện thì người dùng nhập tay
		frappe.db.set_value("Employee", doc.name, "tc_card_id", doc.name, update_modified=False)
		doc.tc_card_id = doc.name


def before_save(doc, method=None):
	"""Đổi ngày hạn khám sức khỏe/tiêm chủng thì nhắc lại từ đầu."""
	before = doc.get_doc_before_save()
	if not before:
		return
	for date_field, level_field, _label in HEALTH_FIELDS:
		if str(doc.get(date_field) or "") != str(before.get(date_field) or ""):
			doc.set(level_field, 0)


def remind_health_records():
	"""Nhắc nhân viên và R02 khi khám sức khỏe hoặc tiêm chủng sắp hết hạn (60/30/7 ngày) hoặc đã hết hạn."""
	day = getdate(today())
	fields = ["name", "employee_name", "user_id"] + [name for pair in HEALTH_FIELDS for name in pair[:2]]
	for employee in frappe.get_all("Employee", filters={"status": "Active"}, fields=fields):
		for date_field, level_field, label in HEALTH_FIELDS:
			expiry = employee.get(date_field)
			if not expiry:
				continue
			days_left = date_diff(expiry, day)
			level = reminders.level_for(days_left)
			if not reminders.is_due(level, employee.get(level_field)):
				continue
			frappe.db.set_value("Employee", employee.name, level_field, level, update_modified=False)
			subject = (
				_("{0} of {1} has expired").format(_(label), employee.employee_name)
				if level == reminders.EXPIRED
				else _("{0} of {1} expires in {2} days").format(_(label), employee.employee_name, days_left)
			)
			notification.emit(
				"HEALTH_RECORD_EXPIRING",
				frappe._dict(doctype="Employee", name=employee.name),
				subject,
				users=[employee.user_id] if employee.user_id else [],
			)
