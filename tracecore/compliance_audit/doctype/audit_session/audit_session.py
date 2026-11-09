"""Audit Session — phiếu giám sát (FEAT-060, ADR-015). Luật ở ``compliance_audit.sessions``."""

from frappe.model.document import Document

from tracecore.compliance_audit import sessions


class AuditSession(Document):
	def validate(self):
		sessions.validate(self)

	def before_submit(self):
		sessions.before_submit(self)

	def on_submit(self):
		sessions.on_submit(self)
