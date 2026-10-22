"""Sterile Putaway: chứng từ nhập kho vô khuẩn / chuyển vị trí (FEAT-025, UC-11, architecture §5.3).

Chỉ dịch vụ kho vô khuẩn (`reprocessing.storage`) tạo và ghi sổ; ghi sổ xong là bất biến và không hủy chứng từ
(chuyển vị trí là một chứng từ mới). Pack giữ vị trí hiện hành, chứng từ này là vết cho cổng T6 và audit.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SterilePutaway(Document):
	def validate(self):
		if not self.flags.tc_storage:
			frappe.throw(_("A Sterile Putaway can only be created by the sterile storage service."))
		if self.action == "Move" and not self.from_location:
			frappe.throw(_("From Location is required to move a pack."))
		if self.action == "Move" and self.from_location == self.location:
			frappe.throw(_("The pack is already on location {0}.").format(self.location))

	def before_cancel(self):
		frappe.throw(_("A Sterile Putaway cannot be cancelled; record a new move instead."))
