"""Sổ tiệt khuẩn điện tử theo máy (FEAT-007, FR-M9-02, A-57 Q1): mỗi mẻ của kỳ một dòng.

Dữ liệu ở `admin_reports.sterilization_log.log_rows`; bản in PDF theo mẫu qua nút Xuất PDF (job nền).
"""

from frappe import _

from tracecore.admin_reports import sterilization_log

CONTEXT = sterilization_log.CONTEXT


def _columns():
	return [
		{"fieldname": "date", "label": _("Date", context=CONTEXT), "fieldtype": "Date", "width": 95},
		{
			"fieldname": "load",
			"label": _("Load", context=CONTEXT),
			"fieldtype": "Link",
			"options": "Sterilization Load",
			"width": 140,
		},
		{
			"fieldname": "equipment_name",
			"label": _("Machine", context=CONTEXT),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "program_name",
			"label": _("Program", context=CONTEXT),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "started_at",
			"label": _("Started At", context=CONTEXT),
			"fieldtype": "Datetime",
			"width": 140,
		},
		{
			"fieldname": "ended_at",
			"label": _("Ended At", context=CONTEXT),
			"fieldtype": "Datetime",
			"width": 140,
		},
		{"fieldname": "params", "label": _("Cycle Parameters"), "fieldtype": "Data", "width": 220},
		{"fieldname": "indicators", "label": _("Indicators"), "fieldtype": "Data", "width": 220},
		{"fieldname": "pack_count", "label": _("Packs", context=CONTEXT), "fieldtype": "Int", "width": 70},
		{"fieldname": "sets", "label": _("Sets", context=CONTEXT), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "operator_name",
			"label": _("Operator", context=CONTEXT),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "unloaded_by_name",
			"label": _("Unloaded By", context=CONTEXT),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "released_by_name",
			"label": _("Released By", context=CONTEXT),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "released_at",
			"label": _("Released At", context=CONTEXT),
			"fieldtype": "Datetime",
			"width": 140,
		},
		{"fieldname": "result", "label": _("Result", context=CONTEXT), "fieldtype": "Data", "width": 100},
	]


def execute(filters=None):
	rows = sterilization_log.log_rows(filters)
	for row in rows:
		row["result"] = _(row["result"], context=CONTEXT)
	return _columns(), rows
