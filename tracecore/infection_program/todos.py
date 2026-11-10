"""Việc cần xử lý của M11 cho bảng chỉ số KSNK và Cổng khoa (FEAT-065; FR-M9-26; hook ``tracecore_ksnk_todos``; A-145 Q3).

Hoạt động quá hạn của kế hoạch năm đã duyệt (FR-M11-05); lọc khoa theo khoa thực hiện của hoạt động.
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

LINK = "/app/tc-ksnk/ke-hoach"
SHOWN_NAMES = 3


def todos(user, department=None, on=None):
	on = getdate(on or today())
	conditions = ""
	values = {"year": on.year, "on": on}
	if department:
		conditions = " and c.department = %(department)s"
		values["department"] = department
	rows = frappe.db.sql(
		f"""
		select c.activity from `tabIC Plan Activity` c join `tabIC Annual Plan` p on p.name = c.parent
		where c.parenttype = 'IC Annual Plan' and p.docstatus = 1 and p.year = %(year)s
			and c.status != 'Completed' and c.due_date < %(on)s{conditions}
		order by c.due_date asc
		""",  # nosec B608 - điều kiện cố định, giá trị qua tham số
		values,
		as_dict=True,
	)
	if not rows:
		return []
	names = [row.activity for row in rows if row.activity]
	return [
		{
			"key": "plan_activity_overdue",
			"severity": "warn",
			"title": _("{0} plan activities overdue").format(len(rows)),
			"count": len(rows),
			"detail": ", ".join(names[:SHOWN_NAMES]) + ("…" if len(names) > SHOWN_NAMES else ""),
			"link": "" if department else LINK,
		}
	]
