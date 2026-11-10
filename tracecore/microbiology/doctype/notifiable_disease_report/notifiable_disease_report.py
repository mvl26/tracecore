"""Notifiable Disease Report (FEAT-069, A-150). Luật ở ``microbiology.notifiable``."""

from frappe.model.document import Document

from tracecore.microbiology import notifiable


class NotifiableDiseaseReport(Document):
	def validate(self):
		notifiable.validate_report(self)

	def before_update_after_submit(self):
		notifiable.guard_after_submit(self)

	def on_cancel(self):
		notifiable.on_cancel(self)
