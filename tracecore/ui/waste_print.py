"""Ngữ cảnh Print Format "TC Waste Receipt": biên nhận thu gom chất thải (FEAT-047, FR-M10-02.6, UC-34 bước 6; A-60 W4).

Hàm được đăng ký ở `hooks.jinja`. Chỉ người đọc được phiếu mới in được. Số kg dùng dấu phẩy thập phân (NFR-L10N-01).
"""

import frappe
from frappe.utils import cint, flt, formatdate, get_datetime

from tracecore.instrument.count_sheet import token_values

DOCTYPE = "Waste Collection"


def _kg(value) -> str:
	text = f"{flt(value):.3f}".rstrip("0").rstrip(".")
	return (text or "0").replace(".", ",")


def _at(value) -> str:
	return f"{formatdate(value, 'dd/mm/yyyy')} {get_datetime(value).strftime('%H:%M')}" if value else ""


def _employee(name) -> str:
	return (frappe.db.get_value("Employee", name, "employee_name") or name or "") if name else ""


def tc_waste_receipt_context(name: str) -> dict:
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	return {
		"tc": token_values(),
		"name": doc.name,
		"draft": doc.docstatus == 0,
		"cancelled": doc.docstatus == 2,
		"department": frappe.db.get_value("Department", doc.department, "department_name") or doc.department,
		"collected_at": _at(doc.collected_at),
		"delivered_by": _employee(doc.delivered_by),
		"collected_by": _employee(doc.collected_by),
		"acknowledged_by": _employee(doc.acknowledged_by),
		"acknowledged_at": _at(doc.acknowledged_at),
		"total_qty": cint(doc.total_containers),
		"total_weight": _kg(doc.total_weight_kg),
		"held_weight": _kg(doc.held_kg) if flt(doc.held_kg) else "",
		"note": doc.note or "",
		"items": [
			{
				"index": row.idx,
				"name": row.waste_type,
				"color": frappe.db.get_value("Waste Type", row.waste_type, "color_code") or "",
				"qty": cint(row.qty),
				"weight": _kg(row.weight_kg),
				"misclassified": cint(row.misclassified),
				"misclass_note": row.misclass_note or "",
			}
			for row in doc.lines
		],
	}
