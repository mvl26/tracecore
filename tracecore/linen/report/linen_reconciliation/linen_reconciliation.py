"""Linen Reconciliation: đối chiếu thu - trả - hủy theo khoa/loại/kỳ (FEAT-035, SCR-18, FR-M3-06, .3, .4; BRU-LIN-004).

Xuất Excel dùng nút Export có sẵn của Script Report. Kỳ không có dữ liệu thì chỉ có dòng tổng bằng 0, không lỗi (FR-M3-06.4).
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from tracecore.linen import reconcile

NUMBERS = ("collected", "returned", "disposed", "new", "variance", "stock")
KG = ("collected_kg", "returned_kg", "disposed_kg", "new_kg", "variance_kg")


def _columns():
	def link(fieldname, label, options, width=150):
		return {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": "Link",
			"options": options,
			"width": width,
		}

	def number(fieldname, label, fieldtype="Int", width=100):
		return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "width": width}

	return [
		link("department", _("Department"), "Department"),
		link("linen_type", _("Linen Type"), "Linen Type"),
		number("collected", _("Collected")),
		number("returned", _("Returned")),
		number("disposed", _("Disposed")),
		number("new", _("Issued New")),
		number("variance", _("Variance")),
		number("variance_pct", _("Variance (%)"), "Float"),
		number("collected_kg", _("Collected (kg)"), "Float"),
		number("returned_kg", _("Returned (kg)"), "Float"),
		number("disposed_kg", _("Disposed (kg)"), "Float"),
		number("variance_kg", _("Variance (kg)"), "Float"),
		number("stock", _("Department Stock")),
		number("min_qty", _("Min")),
		number("max_qty", _("Max")),
	]


def _total(rows):
	total = {"department": _("Total")}
	for key in NUMBERS:
		total[key] = sum(row[key] for row in rows)
	for key in KG:
		total[key] = round(sum(row[key] for row in rows), 3)
	collected = total["collected"]
	total["variance_pct"] = round(100 * total["variance"] / collected, 1) if collected else 0
	return total


def _summary(total):
	return [
		{"label": _("Collected"), "value": total["collected"], "datatype": "Int", "indicator": "blue"},
		{"label": _("Returned"), "value": total["returned"], "datatype": "Int", "indicator": "green"},
		{"label": _("Disposed"), "value": total["disposed"], "datatype": "Int", "indicator": "orange"},
		{
			"label": _("Variance (%)"),
			"value": total["variance_pct"],
			"datatype": "Float",
			"indicator": "red" if abs(total["variance_pct"]) > reconcile.VARIANCE_LIMIT * 100 else "green",
		},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.get("from_date") or today())
	to_date = getdate(filters.get("to_date") or today())
	rows = reconcile.rows(filters.get("department"), filters.get("linen_type"), from_date, to_date)
	total = _total(rows)
	return _columns(), [*rows, total], None, None, _summary(total)
