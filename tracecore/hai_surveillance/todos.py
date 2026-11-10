"""Việc cần xử lý của M13 cho bảng chỉ số KSNK và Cổng khoa (FEAT-065; FR-M9-26; hook ``tracecore_ksnk_todos``; A-145 Q3).

Khoa nội trú chưa có mẫu số ngày hôm qua (FR-M13-03) — cùng điều kiện với nhắc 10:00 của ``reminders.remind_census``.
"""

import frappe
from frappe import _
from frappe.utils import add_days, formatdate, getdate, today

from tracecore.hai_surveillance import census

PORTAL_LINK = "/ksnk-khoa/mau-so"
DESK_LINK = "/app/ward-daily-census"
SHOWN_NAMES = 5


def todos(user, department=None, on=None):
	day = getdate(add_days(on or today(), -1))
	wards = [ward for ward in census.inpatient_wards() if not department or ward.name == department]
	if not wards:
		return []
	entered = set(
		frappe.get_all(
			census.DOCTYPE,
			filters={"census_date": day, "department": ("in", [ward.name for ward in wards])},
			pluck="department",
		)
	)
	missing = [ward.department_name or ward.name for ward in wards if ward.name not in entered]
	if not missing:
		return []
	if department:
		title = _("No daily census for {0}").format(formatdate(day, "dd/mm/yyyy"))
		detail = ""
	else:
		title = _("{0} departments have no daily census for {1}").format(
			len(missing), formatdate(day, "dd/mm/yyyy")
		)
		detail = ", ".join(missing[:SHOWN_NAMES]) + ("…" if len(missing) > SHOWN_NAMES else "")
	return [
		{
			"key": "census_missing",
			"severity": "error",
			"title": title,
			"count": len(missing),
			"detail": detail,
			"link": PORTAL_LINK if department else DESK_LINK,
		}
	]
