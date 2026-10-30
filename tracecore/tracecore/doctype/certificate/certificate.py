"""Certificate: chứng chỉ của nhân viên có hạn và file scan (FEAT-036, FR-M4-02). Quy tắc ở `tracecore.hr.certificates`."""

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.hr import certificates


class Certificate(Document):
	def validate(self):
		certificates.validate_certificate(self)

	def after_insert(self):
		certificates.supersede_renewed(self)

	def on_trash(self):
		frappe.throw(_("Certificates are kept as history and cannot be deleted."), frappe.PermissionError)
