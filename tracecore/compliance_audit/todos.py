"""Việc cần xử lý của M12 cho bảng chỉ số KSNK và Cổng khoa (FEAT-065; FR-M9-26; hook ``tracecore_ksnk_todos``; A-145 Q3).

Phiếu giám sát theo lịch còn thiếu so với chỉ tiêu kỳ hiện tại (FR-M12-03, ``schedule.coverage``).
"""

import frappe
from frappe import _

from tracecore.compliance_audit import schedule, templates

LINK = "/app/tc-ksnk/tuan-thu"


def todos(user, department=None, on=None):
	missing = 0
	departments = set()
	for name in frappe.get_all(schedule.DOCTYPE, filters={"active": 1}, pluck="name"):
		doc = frappe.get_doc(schedule.DOCTYPE, name)
		if frappe.db.get_value(templates.DOCTYPE, doc.audit_template, "docstatus") != 1:
			continue
		for row in schedule.coverage(doc, on):
			if department and row["department"] != department:
				continue
			if row["done"] < row["target"]:
				missing += row["target"] - row["done"]
				departments.add(row["department"])
	if not missing:
		return []
	if department:
		title = _("{0} audits still to do this period").format(missing)
	else:
		title = _("{0} audits still to do this period in {1} departments").format(missing, len(departments))
	return [
		{
			"key": "audit_coverage_low",
			"severity": "warn",
			"title": title,
			"count": missing,
			"detail": "",
			"link": "" if department else LINK,
		}
	]
