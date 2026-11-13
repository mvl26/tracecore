"""Set Issue Request: đề nghị cấp bộ dụng cụ khoa gửi KSNK từ cổng khoa (FEAT-101, A-161, FR-M2-27).

Chỉ dịch vụ `reprocessing.issue_request` tạo và ghi sổ, bằng cờ ``doc.flags.tc_issue_request``. Chứng từ là thông báo:
không giữ chỗ gói, không đổi trạng thái gói hay bộ. Đã ghi sổ thì không hủy, không xóa; trạng thái "đã cấp" suy ra từ
phiếu cấp phát T7 lúc đọc.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SetIssueRequest(Document):
	def validate(self):
		if not self.flags.get("tc_issue_request"):
			frappe.throw(_("An issue request can only be created from the department portal."))

	def before_submit(self):
		if not self.flags.get("tc_issue_request"):
			frappe.throw(_("An issue request can only be created from the department portal."))

	def before_cancel(self):
		frappe.throw(_("An issue request cannot be cancelled; it closes when the sets are issued at T7."))

	def on_trash(self):
		frappe.throw(_("An issue request cannot be deleted."))
