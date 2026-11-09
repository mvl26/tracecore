"""Audit Template — mẫu phiếu giám sát có phiên bản (FEAT-060, ADR-015). Luật ở ``compliance_audit.templates``."""

from frappe.model.document import Document

from tracecore.compliance_audit import templates


class AuditTemplate(Document):
	def autoname(self):
		templates.autoname(self)

	def validate(self):
		templates.validate(self)

	def before_update_after_submit(self):
		templates.guard_locked(self)

	def on_submit(self):
		templates.on_approve(self)
