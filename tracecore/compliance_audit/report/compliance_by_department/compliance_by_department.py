"""Compliance by Department (FEAT-060; FR-M12-11, FR-M12-14, UC-45 bước 5-6).

Tổng hợp phiếu giám sát đã ghi sổ theo mẫu x khoa trong kỳ (``compliance.aggregate``); xuất Excel/PDF bằng nút có sẵn
của Frappe. R08/R12 chỉ nhận khoa của mình; R13 xem tổng hợp, không xem từng phiếu.
"""

import frappe
from frappe import _
from frappe.utils import get_first_day, getdate, today

from tracecore.compliance_audit import compliance


def _columns():
	return [
		{"fieldname": "template_code", "label": _("Template"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "department",
			"label": _("Department"),
			"fieldtype": "Link",
			"options": "Department",
			"width": 200,
		},
		{"fieldname": "sessions", "label": _("Audits"), "fieldtype": "Int", "width": 80},
		{"fieldname": "passed", "label": _("Passed"), "fieldtype": "Int", "width": 80},
		{"fieldname": "scored", "label": _("Sample (n)"), "fieldtype": "Int", "width": 90},
		{"fieldname": "pass_rate", "label": _("Pass Rate"), "fieldtype": "Percent", "width": 90},
		{"fieldname": "avg_score", "label": _("Average Score"), "fieldtype": "Percent", "width": 110},
		{"fieldname": "critical_failed", "label": _("Critical Failed"), "fieldtype": "Int", "width": 110},
		{"fieldname": "rate_label", "label": _("Result"), "fieldtype": "Data", "width": 230},
		{"fieldname": "template_title", "label": _("Template Title"), "fieldtype": "Data", "width": 200},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.from_date = getdate(filters.from_date or get_first_day(today()))
	filters.to_date = getdate(filters.to_date or today())
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date must be before To Date."))
	data = []
	for row in compliance.aggregate(filters):
		row.rate_label = compliance.rate_label(row)
		data.append(row)
	return _columns(), data
