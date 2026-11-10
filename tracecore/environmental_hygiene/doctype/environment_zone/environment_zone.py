"""Environment Zone — vùng vệ sinh (FEAT-070; FR-M15-01; BRU-ENV-001). Luật ở ``environmental_hygiene.zones``."""

from frappe.model.document import Document

from tracecore.environmental_hygiene import zones


class EnvironmentZone(Document):
	def validate(self):
		zones.validate(self)
