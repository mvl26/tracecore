"""Print Job: vết một lần in nhãn (ghi bởi tracecore.core.print).

A-114: nhãn in ra PDF qua hộp thoại In của trình duyệt nên `payload` (ZPL) chỉ còn là vết, có thể trống; job Desk in
bằng máy in chung có thể không có trạm. `Waiting` chỉ còn ở dữ liệu cũ (patch `a114_release_waiting_print_jobs`).
"""

import frappe
from frappe.model.document import Document


class PrintJob(Document):
	pass


def on_doctype_update():
	# đếm in / lịch sử bản in theo chứng từ (Set Unit, Pack…) không quét cả bảng (FEAT-016 G11); chỉ chạy khi JSON
	# DocType đổi (`modified` của print_job.json được nâng cùng thay đổi này)
	frappe.db.add_index("Print Job", ["ref_doctype", "ref_name"])
