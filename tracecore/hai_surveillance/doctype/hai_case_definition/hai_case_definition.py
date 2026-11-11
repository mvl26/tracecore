"""HAI Case Definition — định nghĩa ca NKBV có phiên bản (FEAT-063; FR-M13-01, BRU-HAI-001). Luật ở
``hai_surveillance.definitions``."""

from frappe.model.document import Document

from tracecore.hai_surveillance import definitions


class HAICaseDefinition(Document):
	def autoname(self):
		definitions.autoname(self)

	def validate(self):
		definitions.validate(self)

	def before_update_after_submit(self):
		definitions.guard_locked(self)

	def on_submit(self):
		definitions.on_approve(self)

	def on_trash(self):
		definitions.on_trash(self)
