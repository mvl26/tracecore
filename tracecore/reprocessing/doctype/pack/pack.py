"""Pack: một gói bộ dụng cụ trong một chu trình, tên = Cycle ID (FEAT-018, UC-08, WF-02).

Pack chỉ do dịch vụ đóng gói (`packing.generate`) tạo bằng ``insert(set_name=cycle_id)`` rồi ghi sổ
ngay; không có đường tạo tay từ Desk. Pack không bị hủy chứng từ hay xóa: gói bỏ đi được đánh dấu
``status = Void`` kèm lý do (D12). Chỉ `status`, `void_reason`, `void_note`, `label_print_count` sửa được
sau khi ghi sổ; mọi trường nghiệp vụ khác (hạn dùng, loại gói, snapshot hạn lưu…) bị khóa.

Bốn trường đó cũng chỉ được đổi bởi dịch vụ đóng gói (`packing.reprint`, `packing.void`), bằng cờ
``doc.flags.tc_packing``: R04/System Manager có quyền write (để submit) nhưng lưu từ Desk không được tự mở lại
gói đã hủy (Void → Packed), bỏ qua bước WF-02 hay sửa số lần in.
"""

import frappe
from frappe import _
from frappe.model.document import Document

# `location` (FEAT-025) chỉ đổi qua dịch vụ kho vô khuẩn, `load` (FEAT-022) chỉ qua dịch vụ nạp mẻ, cũng bằng cờ tc_packing
PACKING_FIELDS = ("status", "void_reason", "void_note", "label_print_count", "location", "load")


class Pack(Document):
	def autoname(self):
		# Frappe chỉ gọi autoname khi KHÔNG có set_name: tức là có ai đó tạo Pack mà không qua Cycle ID.
		frappe.throw(_("A Pack is named by its Cycle ID and can only be created by the packing service."))

	def validate(self):
		self._validate_void()

	def before_update_after_submit(self):
		# validate không chạy khi sửa sau ghi sổ, mà hủy hiệu lực (status = Void) lại xảy ra đúng lúc đó
		if not self.flags.tc_packing:
			self._guard_packing_fields()
		self._validate_void()

	def _guard_packing_fields(self):
		before = self.get_doc_before_save()
		changed = [f for f in PACKING_FIELDS if before and str(before.get(f) or "") != str(self.get(f) or "")]
		if changed:
			frappe.throw(
				_(
					"Pack status, void and print count fields are changed only by the packing service: {0}"
				).format(", ".join(changed))
			)

	def _validate_void(self):
		if self.status == "Void" and not self.void_reason:
			frappe.throw(_("Void Reason is required to void a pack."))

	def before_cancel(self):
		frappe.throw(_("A Pack cannot be cancelled; void it instead."))
