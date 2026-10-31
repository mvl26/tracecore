"""Chi phí thuê ngoài xử lý chất thải từ phiếu bàn giao (FEAT-049; FR-M10-04.5; FR-M7-01, FR-M7-02; A-62).

M10 không import M7: `waste.handover` gọi hook `tracecore_after_waste_handover` và `tracecore_after_waste_handover_cancel`.
Khoản chi phí ghi sổ ngay, phân bổ cho các khoa phát sinh theo tỷ lệ kg thu gom. Kỳ chi phí đã khóa thì không chặn phiếu
bàn giao: bỏ qua và ghi chú vào phiếu để R09 xử lý.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from tracecore.costing import entry as costing

ENTRY = "Cost Entry"
SOURCE = "Waste Handover"
CATEGORY = "Outsourcing Cost"
PERCENT_DIGITS = 3


def _allocations(doc):
	kg = {}
	for row in doc.containers:
		if row.department:
			kg[row.department] = kg.get(row.department, 0) + flt(row.weight_kg)
	total = sum(kg.values())
	if total <= 0:
		return []
	rows = [
		{
			"target_type": "Department",
			"target": department,
			"percent": round(weight * 100 / total, PERCENT_DIGITS),
		}
		for department, weight in sorted(kg.items())
	]
	rows[-1]["percent"] = round(100 - sum(row["percent"] for row in rows[:-1]), PERCENT_DIGITS)
	return rows


def on_handover(doc):
	"""Tạo và ghi sổ Cost Entry của phiếu; trả tên khoản hoặc None (không có chi phí hoặc kỳ đã khóa)."""
	allocations = _allocations(doc)
	if flt(doc.total_cost) <= 0 or not allocations:
		return None
	day = getdate(doc.handover_at)
	try:
		costing.check_period_open(day)
	except frappe.ValidationError:
		frappe.clear_last_message()
		doc.add_comment(
			"Comment",
			_("No cost entry was created because the cost period is closed. Enter the cost manually."),
		)
		return None
	entry = frappe.get_doc(
		{
			"doctype": ENTRY,
			"category": CATEGORY,
			"amount": doc.total_cost,
			"source": "Invoice",
			"period_from": day,
			"period_to": day,
			"document_no": doc.name,
			"document_date": day,
			"description": _("From {0} {1}.").format(_(SOURCE), doc.name),
			"source_doctype": SOURCE,
			"source_name": doc.name,
			"allocations": allocations,
		}
	)
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()
	return entry.name


def on_handover_cancel(doc):
	"""Hủy phiếu thì hủy khoản chi phí của phiếu (FR-M10-04.6); kỳ đã khóa thì ghi chú để R09 xử lý."""
	name = frappe.db.get_value(ENTRY, {"source_doctype": SOURCE, "source_name": doc.name, "docstatus": 1})
	if not name:
		return
	entry = frappe.get_doc(ENTRY, name)
	entry.flags.ignore_permissions = True
	entry.flags.ignore_links = True
	try:
		entry.cancel()
	except frappe.ValidationError:
		frappe.clear_last_message()
		doc.add_comment(
			"Comment", _("Cost entry {0} was not cancelled because the cost period is closed.").format(name)
		)
