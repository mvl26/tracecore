"""Stock Alerts: cảnh báo tồn thay dashboard đến khi có FEAT-006 (FEAT-043; FR-M6-06, .1, .3; SCR-26; A-52 C10).

Ba loại dòng: Dưới tồn tối thiểu (theo vật tư và kho), Sắp hết hạn (theo lô, mặc định 30 ngày) và Thiếu cấu hình (vật tư CSSD
chưa có tồn tối thiểu). Dòng Dưới tồn tối thiểu có nút tạo đề nghị mua một chạm (xem stock_alerts.js).
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.inventory import alerts

BELOW, EXPIRING, UNCONFIGURED = "Below minimum", "Expiring", "Not configured"


def _columns():
	return [
		{"fieldname": "alert_type", "label": _("Alert"), "fieldtype": "Data", "width": 150},
		{"fieldname": "item", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 160},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "warehouse",
			"label": _("Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 170,
		},
		{"fieldname": "batch", "label": _("Batch"), "fieldtype": "Link", "options": "Batch", "width": 150},
		{"fieldname": "expiry_date", "label": _("Expiry Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "days_left", "label": _("Days Left"), "fieldtype": "Int", "width": 90},
		{"fieldname": "qty", "label": _("Quantity"), "fieldtype": "Float", "width": 100},
		{"fieldname": "minimum", "label": _("Minimum"), "fieldtype": "Float", "width": 100},
		{"fieldname": "shortfall", "label": _("Shortfall"), "fieldtype": "Float", "width": 100},
		{"fieldname": "action", "label": _("Action"), "fieldtype": "Data", "width": 190},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	wanted = filters.get("alert_type")
	rows = []
	if wanted in (None, "", BELOW):
		rows += [{"alert_type": BELOW, **row} for row in alerts.below_minimum()]
	if wanted in (None, "", EXPIRING):
		days = cint(filters.get("days")) or alerts.EXPIRY_DAYS
		rows += [{"alert_type": EXPIRING, **row} for row in alerts.expiring_batches(days)]
	if wanted in (None, "", UNCONFIGURED):
		rows += [{"alert_type": UNCONFIGURED, **row} for row in alerts.unconfigured_items()]
	return _columns(), rows
