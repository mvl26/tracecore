"""Danh sách bộ / gói để chọn tay trên trạm T1-T8 (M2, A-68), chỉ đọc.

Mỗi bước trả đúng những bộ/gói mà RPC quét của bước đó sẽ chấp nhận về mặt trình tự: T1 bộ đủ điều kiện tiếp nhận; T2-T4 bộ có
cổng liền trước Đạt trong chu trình hiện hành và cổng của bước chưa có kết quả; T5-T8 gói theo trạng thái Pack. Danh sách chỉ để
gợi ý: chọn xong, mã vẫn đi qua đúng hàm kiểm tra như khi quét. Xếp đến trước xếp trước theo thời điểm xong bước trước
(T6-T8 lấy `modified` của Pack, là lần đổi trạng thái gần nhất).
"""

import frappe
from frappe import _
from frappe.utils import cint, format_datetime, today

from tracecore.core import step_gate
from tracecore.core.pick_page import join_label, like, page_of

OPEN_BATCH = ("Running", "Awaiting Result")  # lô rửa còn giữ bộ (A-77)
# bước → (trạng thái Pack, cột thời điểm)
PACK_STEPS = {
	"T5": ("Packed", "pack.packed_at"),
	"T6": ("Released", "pack.modified"),
	"T7": ("In Sterile Stock", "pack.modified"),
	"T8": ("Issued", "pack.modified"),
}
PREVIOUS = {"T2": "T1", "T3": "T2", "T4": "T3"}
STEPS = ("T1", *PREVIOUS, *PACK_STEPS)
# lô/mẻ chờ dỡ để chọn tay ở bước dỡ (A-87): bước → (DocType, bảng con, ``mục đích → trạng thái``)
BATCH_STEPS = {
	"T2": ("Wash Batch", "Wash Batch Set Unit", {None: ("Running", "Awaiting Result")}),
	"T5": (
		"Sterilization Load",
		"Load Pack",
		{"unload": ("Running", "Cycle Complete"), "bi": ("Quarantine",)},
	),
}

SET_COLUMNS = """unit.name as id, set_type.set_type_name as name, unit.department as department,
	department.department_name as department_name, {since} as since"""
PACK_COLUMNS = """pack.name as id, pack.set_name as name, pack.department as department,
	department.department_name as department_name, {since} as since"""


def _set_query(step, department):
	values = {}
	order = ""
	if step == "T1":
		sql = """from `tabSet Unit` unit
			left join `tabInstrument Set Type` set_type on set_type.name = unit.set_type
			left join `tabDepartment` department on department.name = unit.department
			where unit.status in %(statuses)s"""
		values["statuses"] = step_gate.STATION_STATUSES["T1"]
		since = "unit.modified"
		if department:  # ưu tiên bộ thuộc khoa đang giao
			order = "(unit.department = %(department)s) desc, "
			values["department"] = department
	else:
		sql = """from `tabSet Unit` unit
			join `tabStep Gate Result` prev on prev.set_unit = unit.name and prev.cycle_no = unit.current_cycle_no
				and prev.step = %(previous)s and prev.result = 'Pass'
			left join `tabStep Gate Result` this on this.set_unit = unit.name and this.cycle_no = unit.current_cycle_no
				and this.step = %(step)s
			left join `tabInstrument Set Type` set_type on set_type.name = unit.set_type
			left join `tabDepartment` department on department.name = unit.department
			where unit.status in %(statuses)s and ifnull(this.result, 'Pending') = 'Pending'"""
		values.update(previous=PREVIOUS[step], step=step, statuses=step_gate.STATION_STATUSES[step])
		since = "prev.recorded_at"
		if step == "T2":  # bộ trong lô rửa đang chạy không chọn lại được
			sql += """ and not exists (
				select 1 from `tabWash Batch Set Unit` row join `tabWash Batch` batch on batch.name = row.parent
				where row.set_unit = unit.name and batch.status in %(open_batch)s and batch.docstatus = 0)"""
			values["open_batch"] = OPEN_BATCH
		if step == "T4":  # đã có Cycle ID hiệu lực thì phải in lại / hủy nhãn, không đóng gói tiếp
			sql += " and ifnull(unit.active_cycle_id, '') = ''"
	search = ("unit.name", "set_type.set_type_name")
	return sql, values, SET_COLUMNS.format(since=since), since, order, "unit.name", search


def _pack_query(step, department=None):
	status, since = PACK_STEPS[step]
	sql = """from `tabPack` pack left join `tabDepartment` department on department.name = pack.department
		where pack.docstatus = 1 and pack.status = %(status)s"""
	values = {"status": status}
	if step == "T7":  # gói quá hạn không cấp được
		sql += " and pack.expiry >= %(today)s"
		values["today"] = today()
	if step == "T8" and department:  # A-96: gói đã cấp cho khoa
		sql += """ and exists (
			select 1 from `tabIssue Note Pack` row join `tabIssue Note` note on note.name = row.parent
			where row.pack = pack.name and note.docstatus = 1 and note.department = %(department)s)"""
		values["department"] = department
	search = ("pack.name", "pack.set_name", "pack.set_unit")
	return sql, values, PACK_COLUMNS.format(since=since), since, "", "pack.name", search


def suggest(step, q=None, department=None, start=0, page_length=20):
	"""``{"items": [{id, raw, name, department, department_name, since, label}], "total"}`` của bước `step`."""
	start, length = page_of(start, page_length)
	if step not in STEPS:
		return {"items": [], "total": 0}
	sql, values, columns, since, order, key, search = (
		_pack_query(step, department) if step in PACK_STEPS else _set_query(step, department)
	)
	if q and q.strip():
		sql += " and (" + " or ".join(f"{field} like %(like)s" for field in search) + ")"
		values["like"] = like(q.strip())
	count_sql = f"select count(*) {sql}"  # nosec B608 - `sql` ghép từ hằng trong file này, giá trị qua tham số
	total = frappe.db.sql(count_sql, values)[0][0]
	page_sql = (
		f"select {columns} {sql} order by {order}{since} asc, {key} asc limit %(length)s offset %(start)s"  # nosec B608 - như trên
	)
	rows = frappe.db.sql(page_sql, {**values, "length": length, "start": start}, as_dict=True)
	return {"items": [_item(row) for row in rows], "total": total}


def _item(row):
	since = format_datetime(row.since, "dd/MM/yyyy HH:mm") if row.since else None
	return {
		"id": row.id,
		"raw": row.id,
		"name": row.name,
		"department": row.department,
		"department_name": row.department_name,
		"since": row.since,
		"label": join_label(row.id, row.name, row.department_name, since),
	}


def batches(step, purpose=None, equipment=None, q=None, start=0, page_length=20):
	"""Lô rửa / mẻ tiệt khuẩn chờ dỡ của bước `step` (A-87, #1818, #1819), chỉ đọc.

	T2: lô `Running`, `Awaiting Result`. T5: `purpose="unload"` mẻ `Running`, `Cycle Complete`; `purpose="bi"` mẻ `Quarantine`.
	`equipment` giới hạn theo máy đã quét. Trả ``{"items": [{id, raw, equipment, equipment_name, program, program_name,
	started_at, status, count, requires_bi, unloaded, label}], "total"}``; không bao giờ có mã bộ/gói.
	"""
	start, length = page_of(start, page_length)
	config = BATCH_STEPS.get(step)
	statuses = config[2].get(purpose) if config else None
	if not statuses:
		return {"items": [], "total": 0}
	doctype, child, _statuses = config
	is_load = doctype == "Sterilization Load"
	sql = f"""from `tab{doctype}` doc
		left join `tabEquipment` machine on machine.name = doc.equipment
		left join `tabProcess Program` program on program.name = doc.program
		where doc.docstatus < 2 and doc.status in %(statuses)s"""
	values = {"statuses": statuses}
	if equipment:
		sql += " and doc.equipment = %(equipment)s"
		values["equipment"] = equipment
	if q and q.strip():
		sql += """ and (doc.name like %(like)s or doc.equipment like %(like)s
			or machine.equipment_name like %(like)s or program.program_name like %(like)s)"""
		values["like"] = like(q.strip())
	count_sql = f"select count(*) {sql}"  # nosec B608 - `sql` ghép từ hằng trong file này, giá trị qua tham số
	total = frappe.db.sql(count_sql, values)[0][0]
	extra = "doc.requires_bi as requires_bi" if is_load else "0 as requires_bi"
	page_sql = f"""select doc.name as id, doc.equipment, machine.equipment_name, doc.program, program.program_name,
		doc.started_at, doc.status, doc.unload_scan_at, {extra},
		(select count(*) from `tab{child}` row where row.parent = doc.name and row.parenttype = %(doctype)s) as count
		{sql} order by doc.started_at asc, doc.name asc limit %(length)s offset %(start)s"""  # nosec B608 - như trên
	rows = frappe.db.sql(
		page_sql, {**values, "doctype": doctype, "length": length, "start": start}, as_dict=True
	)
	return {"items": [_batch_item(row, doctype) for row in rows], "total": total}


def _batch_item(row, doctype):
	started = format_datetime(row.started_at, "dd/MM/yyyy HH:mm") if row.started_at else None
	return {
		"id": row.id,
		"raw": row.id,
		"equipment": row.equipment,
		"equipment_name": row.equipment_name,
		"program": row.program,
		"program_name": row.program_name,
		"started_at": row.started_at,
		"status": row.status,
		"count": cint(row.count),
		"requires_bi": cint(row.requires_bi),
		"unloaded": bool(row.unload_scan_at),
		"label": join_label(
			row.id,
			f"{row.equipment_name or ''} ({row.equipment})",
			row.program_name or row.program,
			started,
			_("Waiting for release")
			if doctype == "Sterilization Load" and row.unload_scan_at and row.status != "Quarantine"
			else _(row.status, context=doctype),
		),
	}
