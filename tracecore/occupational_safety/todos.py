"""Việc cần xử lý của M16 cho bảng chỉ số KSNK và Cổng khoa (FEAT-065; FR-M9-26; hook ``tracecore_ksnk_todos``; A-145 Q3).

Bước theo dõi phơi nhiễm đến hạn trong 3 ngày hoặc đã quá hạn (FR-M16-04.1). Chỉ đếm số bước — không tên, không mã
hồ sơ (NFR-PRIV-01/02): Cổng khoa không được thấy ai bị phơi nhiễm.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from tracecore.occupational_safety import exposure
from tracecore.occupational_safety.jobs import CHILD, PRE_REMINDER_DAYS


def todos(user, department=None, on=None):
	horizon = add_days(getdate(on or today()), PRE_REMINDER_DAYS)
	conditions = ""
	values = {"horizon": horizon, "status": "Following Up"}
	if department:
		conditions = " and e.department = %(department)s"
		values["department"] = department
	count = frappe.db.sql(
		f"""
		select count(*) from `tab{CHILD}` f join `tab{exposure.DOCTYPE}` e on e.name = f.parent
		where f.parenttype = %(parenttype)s and e.status = %(status)s and f.done_on is null
			and f.due_date is not null and f.due_date <= %(horizon)s{conditions}
		""",  # nosec B608 - tên bảng là hằng của module, giá trị qua tham số
		{**values, "parenttype": exposure.DOCTYPE},
	)[0][0]
	if not count:
		return []
	return [
		{
			"key": "exposure_followup_due",
			"severity": "warn",
			"title": _("{0} exposure follow-up steps due").format(count),
			"count": int(count),
			"detail": "",
			"link": "" if department else exposure.LINK,
		}
	]
