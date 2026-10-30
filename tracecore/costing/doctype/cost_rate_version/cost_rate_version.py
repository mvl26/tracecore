"""Cost Rate Version: bảng định giá có hiệu lực từ ngày, R01 duyệt (FEAT-045, UC-28; architecture §5.3 DT-COSTRATE, A-48).

Controller chỉ chuyển cho `costing.rates` (kiểm dữ liệu, duyệt, tự đóng bản cũ, hủy). Không xóa (on_trash).
"""

import frappe
from frappe.model.document import Document

from tracecore.core import audit
from tracecore.costing import rates


class CostRateVersion(Document):
	def validate(self):
		rates.validate(self)

	def before_submit(self):
		rates.before_submit(self)

	def on_submit(self):
		rates.on_submit(self)

	def before_cancel(self):
		rates.before_cancel(self)

	def on_cancel(self):
		rates.on_cancel(self)

	@frappe.whitelist()
	def fill_from_stock(self):
		"""UC-28 A1: lấy giá bình quân tồn kho cho các dòng vật tư rồi lưu bản Nháp."""
		self.check_permission("write")
		result = rates.fill_from_stock(self)
		self.save()
		return result

	def on_trash(self):
		audit.block_delete(self, "on_trash")
