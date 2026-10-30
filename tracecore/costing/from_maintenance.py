"""Cost Entry Nháp từ hồ sơ bảo trì đã ghi sổ (FEAT-044; FR-M5-04.3 phía M7; UC-27 A1; architecture A-47 C9).

M5 không import M7: `equipment.maintenance.on_submit` gọi hook `tracecore_after_maintenance_submit`, hàm dưới đây (khai báo ở
hooks.py) nhận hồ sơ và tạo khoản chi phí Nháp phân bổ 100 % cho máy để R09 đối chiếu hóa đơn rồi ghi sổ. Kỳ chi phí đã khóa
thì không chặn việc ghi sổ hồ sơ bảo trì: bỏ qua và ghi chú vào hồ sơ để R09 xử lý.
"""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, getdate, today

from tracecore.costing import entry as costing

ENTRY = "Cost Entry"
SOURCE = "Maintenance Record"
# sự cố → Sửa chữa; bảo trì, kiểm định, hiệu chuẩn → Bảo trì
CATEGORIES = {"Incident": "Repair Expense"}
DEFAULT_CATEGORY = "Maintenance Cost"


def on_maintenance_submit(doc):
	"""Tạo Cost Entry Nháp cho hồ sơ `doc` (Maintenance Record) có chi phí > 0; không tạo trùng. Trả tên khoản hoặc None."""
	if flt(doc.cost) <= 0:
		return None
	existing = frappe.db.get_value(
		ENTRY, {"source_doctype": SOURCE, "source_name": doc.name, "docstatus": ["<", 2]}
	)
	if existing:
		return existing
	day = doc.performed_on or today()
	try:
		costing.check_period_open(day)
	except frappe.ValidationError:
		frappe.clear_last_message()
		doc.add_comment(
			"Comment",
			_(
				"No cost entry was created because the cost period is closed. Move the lock date back in Cost Settings and enter the cost manually."
			),
		)
		return None
	entry = frappe.get_doc(
		{
			"doctype": ENTRY,
			"category": CATEGORIES.get(doc.record_type, DEFAULT_CATEGORY),
			"amount": doc.cost,
			"source": "Invoice",
			"period_from": getdate(day),
			"period_to": getdate(day),
			"description": _description(doc),
			"source_doctype": SOURCE,
			"source_name": doc.name,
			"allocations": [{"target_type": "Equipment", "target": doc.equipment, "percent": 100}],
		}
	)
	entry.insert(ignore_permissions=True)
	return entry.name


def _description(doc):
	text = _("From {0} {1} ({2}).").format(
		_(SOURCE), doc.name, _(doc.record_type, context="Maintenance Record")
	)
	parts = [
		_("{0} x {1} = {2}").format(row.part_name, row.qty, fmt_money(row.amount))
		for row in doc.get("parts") or []
	]
	return text if not parts else text + " " + _("Parts: {0}").format("; ".join(parts))
