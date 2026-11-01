"""Daily Test: test hằng ngày của máy tiệt khuẩn, test tự nguyện của máy rửa (FEAT-040, UC-23, architecture §5.3 DT-DAILYTEST).

Chỉ dịch vụ test hằng ngày (`equipment.daily_test`) ghi, bằng cờ ``doc.flags.tc_daily_test``; không sửa sau khi lưu,
không xóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import audit


class DailyTest(Document):
	def validate(self):
		if not self.flags.tc_daily_test:
			frappe.throw(_("A daily test can only be recorded by the daily test service."))
		# dòng được tạo lúc bắt đầu lần chạy, ghi kết quả một lần (A-84)
		before = None if self.is_new() else self.get_doc_before_save()
		if before and (before.result or before.run_status == "Recorded" or not before.run_status):
			frappe.throw(_("A daily test cannot be changed after it is recorded."))

	def on_trash(self):
		audit.block_delete(self, "on_trash")
