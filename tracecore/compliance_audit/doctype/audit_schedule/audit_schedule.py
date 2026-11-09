"""Audit Schedule — lịch giám sát (FEAT-060, FR-M12-03). Luật ở ``compliance_audit.schedule``."""

from frappe.model.document import Document

from tracecore.compliance_audit import schedule


class AuditSchedule(Document):
	def validate(self):
		schedule.validate(self)
