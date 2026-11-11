"""Outbreak Investigation (FEAT-069, A-150). Luật ở ``microbiology.outbreaks``."""

from frappe.model.document import Document

from tracecore.microbiology import outbreaks


class OutbreakInvestigation(Document):
	def validate(self):
		outbreaks.validate(self)

	def before_update_after_submit(self):
		outbreaks.guard_after_submit(self)

	def on_cancel(self):
		outbreaks.on_cancel(self)
