"""Laundry Batch: lô giặt theo kg (FEAT-034, UC-17, FR-M3-03, FR-M3-04, FR-M3-09; architecture §5.3 DT-LAUNDRY, A-50, A-104).

Nghiệp vụ ở `linen.laundry`; controller chỉ nối sự kiện để trạm và form Desk chịu cùng quy tắc. Ghi sổ rồi Hủy, không xóa
(hook `on_trash`).
"""

import frappe
from frappe.model.document import Document

from tracecore.linen import laundry


class LaundryBatch(Document):
	def before_insert(self):
		laundry.before_insert_batch(self)

	def validate(self):
		laundry.validate_batch(self)

	def before_submit(self):
		laundry.before_submit_batch(self)

	@frappe.whitelist()
	def refresh_norm(self):
		"""Form Desk: điền định mức theo máy, chương trình, kg đang chọn mà chưa lưu (server giữ quy tắc, JS không có bản sao)."""
		laundry.fill_norm(self)
