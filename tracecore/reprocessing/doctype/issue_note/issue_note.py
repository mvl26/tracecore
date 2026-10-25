"""Issue Note: phiếu cấp phát nhiều gói cho một khoa tại T7 (FEAT-026, UC-12, architecture §5.3 DT-ISSUE).

Chỉ dịch vụ cấp phát (`reprocessing.issuing`) tạo, sửa phiếu nháp và ghi sổ, bằng cờ ``doc.flags.tc_issuing``.
Phiếu đã ghi sổ không hủy, không xóa (C1): hoàn trả gói là FEAT-027.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class IssueNote(Document):
	def validate(self):
		if not self.flags.tc_issuing:
			frappe.throw(_("An Issue Note can only be created and changed by the issuing service."))
		self.pack_count = len(self.packs or [])

	def before_submit(self):
		if not self.flags.tc_issuing:
			frappe.throw(_("An Issue Note can only be confirmed by the issuing service."))

	def before_cancel(self):
		frappe.throw(_("An Issue Note cannot be cancelled; return the packs instead."))
