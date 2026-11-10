"""RPC tracecore.v1.ksnk_training.* — màn SCR-49 Đào tạo KSNK, sinh viên thực tập (FEAT-059; FR-M11-09..11; UC-42).

- ``status`` (GET, chỉ đọc): tỷ lệ đào tạo KSNK cơ bản theo khoa, chuyên trách/Hội đồng/mạng lưới chưa đạt, sinh viên
  thực tập của năm, số lớp chưa gắn loại KSNK; quyền nhắc của người gọi.
- ``remind`` (POST): R01/R02/R10 gửi ``IC_TRAINING_REMINDER`` cho người chưa học của một khoa (UC-42 A2). R02 gọi từ
  Script Report trên Desk (không mở Page ``tc-ksnk``, A-135 e).

Lỗi nghiệp vụ trả body ``{ok: false, error: {title, reason, action}}`` để màn hiện ``alert-error`` inline.
"""

import frappe
from frappe import _
from frappe.utils import nowdate

from tracecore.infection_program import training
from tracecore.ui import ksnk

REMIND_ROLES = ("TC R01", "TC R02", "TC R10", "System Manager")


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == training.SCREEN_SLUG)
	if not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(
			_("You are not allowed to open the infection control training screen."), frappe.PermissionError
		)


def _can_remind():
	return bool(set(frappe.get_roles()) & set(REMIND_ROLES))


def _public(row):
	"""Bỏ user_id khỏi danh sách chưa học gửi về màn."""
	row = dict(row)
	row["untrained"] = [
		{"employee": person["employee"], "employee_name": person["employee_name"]}
		for person in row["untrained"]
	]
	return row


@frappe.whitelist(methods=["GET"])
def status(year=None, department=None):
	"""Dữ liệu SCR-49 cho năm (mặc định năm nay) và khoa (tùy chọn)."""
	_require_screen()
	year = training.check_year(year or nowdate()[:4])
	department = department or None
	basic = training.basic_rows(year, department)
	basic["departments"] = [_public(row) for row in basic["departments"]]
	return {
		"year": year,
		"target": basic["target"],
		"basic": basic,
		"core": training.core_rows(year, department),
		"trainees": training.trainee_rows(year, department),
		"can_remind": _can_remind(),
	}


@frappe.whitelist(methods=["POST"])
def remind(department, year=None):
	"""Nhắc người chưa học KSNK cơ bản của khoa ``department`` trong năm (UC-42 A2)."""
	if not _can_remind():
		frappe.throw(_("You are not allowed to send training reminders."), frappe.PermissionError)
	if not department:
		return {
			"ok": False,
			"error": {
				"title": _("Reminder not sent"),
				"reason": _("No department was chosen."),
				"action": _("Choose a department and send again."),
			},
		}
	result = training.remind(department, year or nowdate()[:4])
	return {"ok": True, **result}
