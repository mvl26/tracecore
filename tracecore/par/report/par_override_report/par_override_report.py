"""Par Override Report (SCR-31, FR-M8-04.3): báo cáo ghi đè cơ số theo tháng cho QLCL (FEAT-032).

Một dòng cho mỗi đề nghị trong khoảng ngày (theo ``requested_at``). Phần tóm tắt có KPI của SRS (dòng "Bộ vượt cơ số
được ghi đè", mục tiêu ≤ 10 %): số ghi đè Approved ÷ số bộ chuyển Hết vòng đời do vượt cơ số trong cùng khoảng (A-18 Q12).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_first_day, get_last_day, getdate, today

KPI_TARGET = 10  # % (srs.md, KPI "Bộ vượt cơ số được ghi đè")
FIELDS = [
	"name",
	"set_unit",
	"set_type",
	"department",
	"status",
	"requested_by",
	"requested_at",
	"reason",
	"cycles_used",
	"max_cycles",
	"extra_cycles",
	"cycles_consumed",
	"valid_until",
	"decided_by",
	"decided_at",
	"decision_reason",
]


def _columns():
	def link(fieldname, label, options, width=140):
		return {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": "Link",
			"options": options,
			"width": width,
		}

	def data(fieldname, label, width=120, fieldtype="Data"):
		return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "width": width}

	return [
		link("name", _("Override"), "Par Override", 150),
		link("set_unit", _("Set Unit"), "Set Unit", 190),
		link("set_type", _("Set Type"), "Instrument Set Type", 120),
		link("department", _("Department"), "Department", 150),
		data("status", _("Status"), 110),
		link("requested_by", _("Requested By"), "User", 160),
		data("requested_at", _("Requested At"), 150, "Datetime"),
		data("reason", _("Reason for Request"), 240),
		data("cycles_used", _("Cycles Used"), 100, "Int"),
		data("max_cycles", _("Max Cycles"), 100, "Int"),
		data("extra_cycles", _("Extra Cycles"), 100, "Int"),
		data("cycles_consumed", _("Cycles Consumed"), 120, "Int"),
		data("valid_until", _("Valid Until"), 110, "Date"),
		link("decided_by", _("Decided By"), "User", 160),
		data("decided_at", _("Decided At"), 150, "Datetime"),
		data("decision_reason", _("Reason for Decision"), 240),
	]


def _range(filters):
	"""``(từ ngày, đến ngày)``; mặc định cả tháng trước (báo cáo QLCL gửi đầu tháng)."""
	first = get_first_day(add_days(get_first_day(today()), -1))
	start = getdate(filters.get("from_date") or first)
	end = getdate(filters.get("to_date") or get_last_day(start))
	return start, end


def _exceeded_sets(start, end):
	"""Số bộ khác nhau chuyển Hết vòng đời do vượt cơ số trong khoảng ngày (Audit Log của ``step_gate``)."""
	return len(
		set(
			frappe.get_all(
				"Audit Log",
				filters={
					"ref_doctype": "Set Unit",
					"action": "Update",
					"reason": "Par Exceeded",
					"creation": ["between", [start, f"{end} 23:59:59.999999"]],
				},
				pluck="ref_name",
			)
		)
	)


def _summary(rows, start, end):
	approved = sum(1 for row in rows if row.status == "Approved" or row.status == "Expired")
	exceeded = _exceeded_sets(start, end)
	rate = round(100 * approved / exceeded, 1) if exceeded else 0
	return [
		{"label": _("Override Requests"), "value": len(rows), "datatype": "Int", "indicator": "blue"},
		{"label": _("Approved Overrides"), "value": approved, "datatype": "Int", "indicator": "green"},
		{"label": _("Sets at Their Limit"), "value": exceeded, "datatype": "Int", "indicator": "orange"},
		{
			"label": _("Overridden Share (%) (target ≤ {0})").format(KPI_TARGET),
			"value": rate,
			"datatype": "Float",
			"indicator": "red" if rate > KPI_TARGET else "green",
		},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	start, end = _range(filters)
	conditions = {"requested_at": ["between", [start, f"{end} 23:59:59.999999"]], "docstatus": ["<", 3]}
	for key in ("status", "department", "set_type"):
		if filters.get(key):
			conditions[key] = filters[key]
	rows = frappe.get_list(
		"Par Override", filters=conditions, fields=FIELDS, order_by="requested_at asc, name asc"
	)
	for row in rows:
		row.cycles_used, row.max_cycles = cint(row.cycles_used), cint(row.max_cycles)
		row.status = _(row.status, context="Par Override")
	return _columns(), [dict(row) for row in rows], None, None, _summary(rows, start, end)
