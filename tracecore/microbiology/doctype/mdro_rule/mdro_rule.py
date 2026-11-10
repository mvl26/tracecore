"""MDRO Rule — quy tắc đa kháng có phiên bản (FEAT-067, BRU-MDR-001). Luật ở ``microbiology.rules``."""

from frappe.model.document import Document

from tracecore.microbiology import rules


class MDRORule(Document):
	def autoname(self):
		rules.autoname(self)

	def validate(self):
		rules.validate(self)

	def before_update_after_submit(self):
		rules.guard_locked(self)

	def on_submit(self):
		rules.on_approve(self)
