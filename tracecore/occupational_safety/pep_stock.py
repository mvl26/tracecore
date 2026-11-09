"""Thuốc dự phòng sau phơi nhiễm (FEAT-071; FR-M16-08, FR-M16-08.1; A-137 h).

Item đánh dấu `tc_is_pep_drug`; đọc thẳng tồn ERPNext (`Bin`, `Item Reorder`, `Batch`), không nhập lại, không import
`tracecore.inventory`. Dưới mức tối thiểu của kho hoặc lô còn tồn hết hạn trong ≤ 30 ngày → báo R01.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from tracecore.core import notification

EXPIRY_DAYS = 30


def pep_items():
	return frappe.get_all("Item", filters={"tc_is_pep_drug": 1, "disabled": 0}, pluck="name")


def status(day=None):
	"""Danh sách cảnh báo hiện tại: [{kind: below_min|expiring, item, warehouse|batch, qty, level|expiry_date, days}]."""
	day = getdate(day or today())
	items = pep_items()
	if not items:
		return []
	alerts = []
	for row in frappe.get_all(
		"Item Reorder",
		filters={"parenttype": "Item", "parent": ["in", items]},
		fields=["parent as item", "warehouse", "warehouse_reorder_level as level"],
	):
		if not flt(row.level):
			continue
		qty = flt(frappe.db.get_value("Bin", {"item_code": row.item, "warehouse": row.warehouse}, "actual_qty"))
		if qty < flt(row.level):
			alerts.append(
				{"kind": "below_min", "item": row.item, "warehouse": row.warehouse, "qty": qty, "level": flt(row.level)}
			)
	for batch in frappe.get_all(
		"Batch",
		filters={
			"item": ["in", items],
			"disabled": 0,
			"batch_qty": [">", 0],
			"expiry_date": ["<=", add_days(day, EXPIRY_DAYS)],
		},
		fields=["name", "item", "batch_qty", "expiry_date"],
		order_by="expiry_date",
	):
		alerts.append(
			{
				"kind": "expiring",
				"item": batch.item,
				"batch": batch.name,
				"qty": flt(batch.batch_qty),
				"expiry_date": str(batch.expiry_date),
				"days": (getdate(batch.expiry_date) - day).days,
			}
		)
	return alerts


def check(day=None):
	"""Việc hằng ngày: có cảnh báo → một thông báo PEP_STOCK_ALERT cho R01 (Rule mặc định)."""
	alerts = status(day)
	if not alerts:
		return alerts
	below = sum(1 for a in alerts if a["kind"] == "below_min")
	expiring = len(alerts) - below
	notification.emit(
		"PEP_STOCK_ALERT",
		subject=_("Post-exposure prophylaxis stock: {0} below minimum, {1} batches expiring within {2} days").format(
			below, expiring, EXPIRY_DAYS
		),
		link="/app/tc-ksnk/phoi-nhiem",
	)
	return alerts
