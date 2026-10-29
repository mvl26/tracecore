"""Cảnh báo tồn dưới tối thiểu, lô sắp hết hạn, vật tư thiếu cấu hình và đề nghị mua một chạm (FEAT-043; FR-M6-06, .1-.3;
UC-26 bước 6, E3; architecture A-52 C7-C12).

Tồn tối thiểu theo kho là bảng `reorder_levels` của Item (FEAT-041); vật tư xét là Item nhóm CSSD (`tc_item_group_cssd`) đang
dùng. Vật tư chưa có mức tối thiểu không bị cảnh báo tồn mà vào danh sách "thiếu cấu hình". Job `run_daily` phát hai sự kiện
thông báo (email cho R09); `overview` là nguồn của Script Report `Stock Alerts` thay dashboard đến khi có FEAT-006.
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, getdate, today

from tracecore.core import notification
from tracecore.core.errors import Block, BlockedError
from tracecore.inventory import consume

EXPIRY_DAYS = 30  # FR-M6-06.1
BELOW_EVENT = "STOCK_BELOW_MIN"
EXPIRING_EVENT = "BATCH_EXPIRING"
REQUEST = "Material Request"


def _items():
	"""Item CSSD đang dùng và quản lý tồn: ``{tên: {"name", "item_name", "stock_uom"}}``."""
	rows = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_stock_item": 1, "tc_item_group_cssd": ["is", "set"]},
		fields=["name", "item_name", "stock_uom", "has_batch_no"],
		order_by="name asc",
	)
	return {row.name: row for row in rows}


def _levels():
	return frappe.get_all(
		"Item Reorder",
		filters={"parenttype": "Item", "warehouse_reorder_level": [">", 0]},
		fields=["parent", "warehouse", "warehouse_reorder_level", "warehouse_reorder_qty"],
		order_by="parent asc, idx asc",
	)


def below_minimum():
	"""Cặp (vật tư, kho) có tồn thực tế dưới mức tối thiểu của kho: item, kho, tồn, tối thiểu, phần thiếu, số lượng nên mua."""
	items = _items()
	rows = []
	for level in _levels():
		if level.parent not in items:
			continue
		qty = flt(
			frappe.db.get_value(
				"Bin", {"item_code": level.parent, "warehouse": level.warehouse}, "actual_qty"
			)
		)
		minimum = flt(level.warehouse_reorder_level)
		if qty >= minimum:
			continue
		shortfall = flt(minimum - qty)
		rows.append(
			{
				"item": level.parent,
				"item_name": items[level.parent].item_name,
				"warehouse": level.warehouse,
				"qty": qty,
				"minimum": minimum,
				"shortfall": shortfall,
				"reorder_qty": flt(level.warehouse_reorder_qty) or shortfall,
				"uom": items[level.parent].stock_uom,
			}
		)
	return rows


def expiring_batches(days=EXPIRY_DAYS):
	"""Lô còn tồn có hạn trong `days` ngày tới hoặc đã quá hạn (``days_left`` âm), theo hạn tăng dần."""
	limit = getdate(add_days(today(), days))
	rows = {}
	for name, item in _items().items():
		if not item.has_batch_no:
			continue
		for lot in consume._stock_by_lot(name):
			if not lot.expiry or getdate(lot.expiry) > limit:
				continue
			row = rows.setdefault(
				lot.batch,
				{
					"item": name,
					"item_name": item.item_name,
					"batch": lot.batch,
					"expiry_date": getdate(lot.expiry),
					"days_left": date_diff(lot.expiry, today()),
					"qty": 0,
					"warehouse": lot.warehouse,
				},
			)
			row["qty"] += lot.qty
	return sorted(rows.values(), key=lambda row: (row["expiry_date"], row["batch"]))


def unconfigured_items():
	"""Item CSSD chưa có mức tồn tối thiểu ở kho nào (FR-M6-06.3): không cảnh báo tồn, chỉ liệt kê để cấu hình."""
	configured = {level.parent for level in _levels()}
	return [
		{"item": name, "item_name": item.item_name}
		for name, item in _items().items()
		if name not in configured
	]


def overview():
	return {
		"below_minimum": below_minimum(),
		"expiring": expiring_batches(),
		"unconfigured": unconfigured_items(),
	}


# --- job hằng ngày --------------------------------------------------------------------------------------------


def _send(event, doctype, name, subject):
	"""Báo R09 qua `core.notification`; lỗi gửi chỉ ghi Error Log, không dừng job. Trả True nếu gửi lỗi."""
	try:
		notification.emit(event, frappe._dict(doctype=doctype, name=name), subject)
	except Exception:
		frappe.log_error(title=f"FEAT-043 notify {event} {name}")
		return True
	return False


def run_daily():
	"""Cron 06:00: gửi thông báo cho từng vật tư dưới tồn tối thiểu và từng lô sắp hết hạn còn tồn (FR-M6-06, .1)."""
	summary = {"below_minimum": 0, "expiring": 0, "unconfigured": len(unconfigured_items()), "failed": 0}
	for row in below_minimum():
		summary["below_minimum"] += 1
		summary["failed"] += _send(
			BELOW_EVENT,
			"Item",
			row["item"],
			_("{0} is below the minimum stock of warehouse {1}: {2} of {3}").format(
				row["item"], row["warehouse"], row["qty"], row["minimum"]
			),
		)
	for row in expiring_batches():
		summary["expiring"] += 1
		summary["failed"] += _send(
			EXPIRING_EVENT,
			"Batch",
			row["batch"],
			_("Batch {0} of {1} expires on {2} ({3} in stock)").format(
				row["batch"], row["item"], row["expiry_date"], row["qty"]
			),
		)
	return summary


# --- đề nghị mua một chạm (FR-M6-06.2) ------------------------------------------------------------------------


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _open_request(item, warehouse):
	"""Đề nghị mua Purchase đang còn hiệu lực cho cặp (vật tư, kho): bản Nháp, hoặc đã ghi sổ nhưng chưa đặt/nhận đủ (không
	tạo thêm khi hàng đang về, tránh đặt trùng)."""
	names = frappe.get_all(
		"Material Request Item",
		filters={"item_code": item, "warehouse": warehouse, "docstatus": ["<", 2], "parenttype": REQUEST},
		pluck="parent",
		order_by="creation asc",
	)
	for name in dict.fromkeys(names):
		row = frappe.db.get_value(
			REQUEST,
			name,
			["material_request_type", "docstatus", "status", "per_ordered", "per_received"],
			as_dict=True,
		)
		if row.material_request_type != "Purchase":
			continue
		if row.docstatus == 0 or (
			row.status not in ("Stopped", "Cancelled", "Received", "Ordered")
			and flt(row.per_ordered) < 100
			and flt(row.per_received) < 100
		):
			return frappe.get_doc(REQUEST, name)
	return None


def create_purchase_request(item, warehouse):
	"""Tạo `Material Request` Mua Nháp một dòng cho cặp (vật tư, kho) đang dưới tồn tối thiểu; đã có Nháp mở thì trả lại nó."""
	valid = (
		isinstance(item, str)
		and isinstance(warehouse, str)
		and frappe.db.exists("Item", item)
		and frappe.db.exists("Warehouse", warehouse)
	)
	if not valid:
		raise _blocked(
			"PURCHASE_ITEM_INVALID",
			_("Item or warehouse is not valid"),
			_("Item {0} or warehouse {1} does not exist.").format(item or "-", warehouse or "-"),
			_("Choose the alert row again."),
		)
	row = next((r for r in below_minimum() if r["item"] == item and r["warehouse"] == warehouse), None)
	if not row:
		raise _blocked(
			"PURCHASE_NOT_NEEDED",
			_("Stock is not below the minimum"),
			_("{0} is not below its minimum stock in warehouse {1}.").format(item, warehouse),
			_("Set a minimum stock on the item, or restock from the stock alert list."),
		)
	existing = _open_request(item, warehouse)
	if existing:
		return existing
	due = add_days(today(), 7)
	doc = frappe.get_doc(
		{
			"doctype": REQUEST,
			"material_request_type": "Purchase",
			"company": frappe.db.get_value("Warehouse", warehouse, "company"),
			"transaction_date": today(),
			"schedule_date": due,
			"items": [
				{
					"item_code": item,
					"qty": row["reorder_qty"],
					"uom": row["uom"],
					"warehouse": warehouse,
					"schedule_date": due,
				}
			],
		}
	)
	return doc.insert()
