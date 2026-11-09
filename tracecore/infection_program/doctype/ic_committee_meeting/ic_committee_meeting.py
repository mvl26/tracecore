"""IC Committee Meeting — biên bản họp Hội đồng KSNK (FEAT-058; FR-M11-08). Logic ở ``meetings``."""

from frappe.model.document import Document

from tracecore.infection_program import meetings


class ICCommitteeMeeting(Document):
	def validate(self):
		meetings.validate(self)

	def on_submit(self):
		meetings.on_submit(self)

	def on_cancel(self):
		meetings.on_cancel(self)
