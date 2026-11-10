"""Environmental Limit — ngưỡng môi trường có phiên bản (FEAT-070; FR-M15-03; BRU-ENV-002). Luật ở
``environmental_hygiene.limits``."""

from frappe.model.document import Document

from tracecore.environmental_hygiene import limits


class EnvironmentalLimit(Document):
	def autoname(self):
		limits.autoname(self)

	def validate(self):
		limits.validate(self)

	def before_update_after_submit(self):
		limits.guard_locked(self)

	def on_submit(self):
		limits.on_approve(self)
