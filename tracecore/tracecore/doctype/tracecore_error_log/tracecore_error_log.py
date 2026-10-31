"""Nhật ký lỗi (FEAT-052, A-71, FR-M9-20): chỉ dịch vụ `core.error_codes` ghi, không xóa được."""

import frappe
from frappe import _
from frappe.model.document import Document


class TraceCoreErrorLog(Document):
	def on_trash(self):
		frappe.throw(_("The error log cannot be deleted."))
