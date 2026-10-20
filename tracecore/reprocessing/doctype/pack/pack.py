"""Pack: một gói bộ dụng cụ trong một chu trình, tên = Cycle ID (FEAT-018, UC-08, WF-02).

Pack chỉ do dịch vụ đóng gói (`packing.generate`, Task 8) tạo bằng ``insert(set_name=cycle_id)`` rồi ghi sổ
ngay; không có đường tạo tay từ Desk. Pack không bị hủy chứng từ hay xóa: gói bỏ đi được đánh dấu
``status = Void`` kèm lý do (D12). Chỉ `status`, `void_reason`, `void_note`, `label_print_count` sửa được
sau khi ghi sổ; mọi trường nghiệp vụ khác (hạn dùng, loại gói, snapshot hạn lưu…) bị khóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class Pack(Document):
	def autoname(self):
		# Frappe chỉ gọi autoname khi KHÔNG có set_name: tức là có ai đó tạo Pack mà không qua Cycle ID.
		frappe.throw(_("A Pack is named by its Cycle ID and can only be created by the packing service."))

	def validate(self):
		self._validate_void()

	def before_update_after_submit(self):
		# validate không chạy khi sửa sau ghi sổ, mà hủy hiệu lực (status = Void) lại xảy ra đúng lúc đó
		self._validate_void()

	def _validate_void(self):
		if self.status == "Void" and not self.void_reason:
			frappe.throw(_("Void Reason is required to void a pack."))

	def before_cancel(self):
		frappe.throw(_("A Pack cannot be cancelled; void it instead."))
