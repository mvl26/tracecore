"""Cost Entry: khoản chi phí theo kỳ, phân bổ cho thiết bị/khu/chương trình (FEAT-044, UC-27; architecture §5.3 DT-COSTENTRY, A-47).

Controller chỉ chuyển cho `costing.entry` (kiểm dữ liệu, khóa kỳ, phân bổ theo ngày). Không xóa (on_trash).
"""

from frappe.model.document import Document

from tracecore.core import audit
from tracecore.costing import entry


class CostEntry(Document):
	def validate(self):
		entry.validate(self)

	def before_submit(self):
		entry.before_submit(self)

	def before_cancel(self):
		entry.check_period_open(self.period_from)

	def on_trash(self):
		audit.block_delete(self, "on_trash")
