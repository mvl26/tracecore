"""Dirty Return Request: yêu cầu lấy đồ bẩn khoa gửi KSNK từ cổng khoa (FEAT-100, A-160, FR-M2-26).

Chỉ dịch vụ `reprocessing.dirty_return` tạo và ghi sổ, bằng cờ ``doc.flags.tc_dirty_return``. Chứng từ là thông báo: không
đổi trạng thái Set Unit hay Pack (BRU-FLOW-003). Đã ghi sổ thì không hủy, không xóa; trạng thái "đã tiếp nhận" suy ra
từ phiếu tiếp nhận T1 lúc đọc.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class DirtyReturnRequest(Document):
	def validate(self):
		if not self.flags.get("tc_dirty_return"):
			frappe.throw(_("A pickup request can only be created from the department portal."))

	def before_submit(self):
		if not self.flags.get("tc_dirty_return"):
			frappe.throw(_("A pickup request can only be created from the department portal."))

	def before_cancel(self):
		frappe.throw(_("A pickup request cannot be cancelled; it closes when the sets are received at T1."))

	def on_trash(self):
		frappe.throw(_("A pickup request cannot be deleted."))
