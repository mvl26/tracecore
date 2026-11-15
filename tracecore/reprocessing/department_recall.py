"""Lệnh thu hồi nhìn từ khoa (FEAT-101, A-161, FR-M9-32; cổng khoa của Page tc-flow, UC-14 bước 5).

Chỉ đọc. Lệnh đang mở là `Recall Order` còn Nháp (`docstatus = 0`, `status = Open`); đóng lệnh mới ghi sổ. Xác nhận từng
gói vẫn đi qua `reprocessing.recall.confirm_pack` (RPC `tracecore.v1.recall.confirm_pack`), quy tắc vai trò không đổi.
Mã bệnh nhân chỉ trả dạng đã che (`patient_code_masked`).
"""

import frappe

_OPEN = "recall.docstatus = 0 and recall.status = 'Open'"


def pending_count(department):
	"""Số gói của khoa trong lệnh thu hồi đang mở mà chưa được xác nhận."""
	return int(
		frappe.db.sql(
			f"""select count(*) from `tabRecall Order Pack` line
			join `tabRecall Order` recall on recall.name = line.parent and line.parenttype = 'Recall Order'
			where {_OPEN} and line.department = %s and ifnull(line.line_status, '') != 'Confirmed'""",  # nosec B608
			(department,),
		)[0][0]
		or 0
	)


def open_orders(department):
	"""Lệnh thu hồi đang mở có gói của khoa, cũ trước: ``[{recall, reason, trigger, opened_at, lines: [...]}]``."""
	rows = frappe.db.sql(
		f"""select recall.name as recall, recall.reason, recall.trigger, recall.opened_at,
			recall.sterilization_load, recall.indicator_lot,
			line.pack as cycle_id, line.set_unit as set_id, line.status_at_recall, line.action,
			line.patient_code_masked, line.line_status, line.confirmed_by, line.confirmed_at
		from `tabRecall Order Pack` line
		join `tabRecall Order` recall on recall.name = line.parent and line.parenttype = 'Recall Order'
		where {_OPEN} and line.department = %s
		order by recall.opened_at asc, recall.name asc, line.idx asc""",  # nosec B608
		(department,),
		as_dict=True,
	)
	orders = {}
	for row in rows:
		order = orders.setdefault(
			row.recall,
			{
				"recall": row.recall,
				"reason": row.reason,
				"trigger": row.trigger,
				"opened_at": row.opened_at,
				"sterilization_load": row.sterilization_load,
				"indicator_lot": row.indicator_lot,
				"lines": [],
			},
		)
		order["lines"].append(
			{
				"cycle_id": row.cycle_id,
				"set_id": row.set_id,
				"status_at_recall": row.status_at_recall,
				"action": row.action,
				"patient_code_masked": row.patient_code_masked,
				"confirmed": row.line_status == "Confirmed",
				"confirmed_by": row.confirmed_by,
				"confirmed_at": row.confirmed_at,
			}
		)
	return list(orders.values())
