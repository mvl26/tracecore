"""Communicable Disease (FEAT-069, A-150). Luật ở ``microbiology.notifiable``."""

from frappe.model.document import Document

from tracecore.microbiology import notifiable


class CommunicableDisease(Document):
	def validate(self):
		notifiable.validate_disease(self)
