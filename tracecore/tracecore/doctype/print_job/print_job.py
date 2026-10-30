"""Print Job: một lệnh in nhãn trong hàng đợi (ghi bởi tracecore.core.print).

`Waiting` = chưa có máy in đúng loại nhãn nên chưa có ZPL (`payload` trống); `set_roll` render rồi chuyển `Queued`.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class PrintJob(Document):
	def validate(self):
		if self.status == "Queued" and not self.payload:
			frappe.throw(_("A queued print job needs label content."))


def on_doctype_update():
	# đếm in / lịch sử bản in theo chứng từ (Set Unit, Pack…) không quét cả bảng (FEAT-016 G11); chỉ chạy khi JSON
	# DocType đổi (`modified` của print_job.json được nâng cùng thay đổi này)
	frappe.db.add_index("Print Job", ["ref_doctype", "ref_name"])
