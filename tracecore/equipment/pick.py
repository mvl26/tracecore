"""Gợi ý thiết bị cho chọn tay trên trạm (M5, A-68): máy `Ready` theo loại máy của bước, tìm theo mã hoặc tên.

Chỉ đọc. Chọn tay không thay kiểm tra: mã chọn được vẫn đi qua RPC quét (`washing.scan_machine`, `sterilizing`…).
"""

import frappe

from tracecore.core.pick_page import join_label, like, page_of
from tracecore.equipment import daily_test

# Loại máy mỗi bước dùng (architecture §5.3, Equipment.equipment_type)
STEP_TYPES = {
	"T2": ("Washer-Disinfector", "Ultrasonic Cleaner"),
	"T4": ("Sealer",),
	"T5": ("Steam Sterilizer", "Plasma Sterilizer"),
	"LIN": ("Laundry Washer", "Dryer"),
}
PURPOSE_DAILY_TEST = "daily_test"


def types_for(step, purpose=None):
	"""Loại máy gợi ý cho bước `step`; mục đích ``daily_test`` là mọi loại máy có test hằng ngày. Không có → ``()``."""
	if purpose == PURPOSE_DAILY_TEST:
		return tuple(daily_test.REQUIRED)
	return STEP_TYPES.get(step, ())


def suggest(equipment_types, q=None, start=0, page_length=20):
	"""``{"items": [{id, name, type, label}], "total"}`` của máy `Ready` thuộc `equipment_types`."""
	start, length = page_of(start, page_length)
	if not equipment_types:
		return {"items": [], "total": 0}
	where = "status = 'Ready' and equipment_type in %(types)s"
	values = {"types": tuple(equipment_types)}
	if q and q.strip():
		where += " and (name like %(like)s or equipment_name like %(like)s)"
		values["like"] = like(q.strip())
	count_sql = f"select count(*) from `tabEquipment` where {where}"  # nosec B608 - `where` ghép từ hằng, giá trị qua tham số
	total = frappe.db.sql(count_sql, values)[0][0]
	page_sql = f"select name, equipment_name, equipment_type from `tabEquipment` where {where} order by name asc limit %(length)s offset %(start)s"  # nosec B608 - như trên
	rows = frappe.db.sql(page_sql, {**values, "length": length, "start": start}, as_dict=True)
	items = [
		{
			"id": row.name,
			"name": row.equipment_name,
			"type": row.equipment_type,
			"label": join_label(row.name, row.equipment_name),
		}
		for row in rows
	]
	return {"items": items, "total": total}
