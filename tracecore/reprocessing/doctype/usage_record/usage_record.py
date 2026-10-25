"""Usage Record: một lần quét sử dụng gói tại khoa (T8, FEAT-027, UC-13, architecture §5.3 DT-USAGE).

Chỉ dịch vụ sử dụng (`reprocessing.usage`) tạo, sửa và ghi sổ, bằng cờ ``doc.flags.tc_usage``. Mã bệnh nhân là trường
Password (mã hóa trong `__Auth`); chỗ hiển thị dùng `patient_code_masked` (che 4 ký tự giữa). Mỗi gói có tối đa một
bản ghi và bản ghi đã ghi sổ không hủy, không xóa: Cycle ID đã dùng không bao giờ được kích hoạt lại (BRU-ID-003).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password

HIDDEN = 4  # FR-M2-17.1: ẩn 4 ký tự giữa


def mask_patient_code(code):
	"""Che ``HIDDEN`` ký tự giữa của mã bệnh nhân; mã không dài hơn ``HIDDEN`` ký tự thì che hết."""
	text = code or ""
	if len(text) <= HIDDEN:
		return "*" * len(text)
	left = (len(text) - HIDDEN) // 2
	return text[:left] + "*" * HIDDEN + text[left + HIDDEN :]


class UsageRecord(Document):
	@property
	def patient_code_masked(self):
		if not self.name or self.is_new():
			return ""
		code = get_decrypted_password("Usage Record", self.name, "patient_code", raise_exception=False)
		return mask_patient_code(code)

	def validate(self):
		if not self.flags.tc_usage:
			frappe.throw(_("A Usage Record can only be created and changed by the usage service."))
		if self.is_new() and frappe.db.exists("Usage Record", {"pack": self.pack, "docstatus": ["<", 2]}):
			frappe.throw(_("Pack {0} already has a usage record.").format(self.pack))

	def before_submit(self):
		if not self.flags.tc_usage:
			frappe.throw(_("A Usage Record can only be confirmed by the usage service."))

	def before_cancel(self):
		frappe.throw(_("A Usage Record cannot be cancelled; a used Cycle ID is never reactivated."))
