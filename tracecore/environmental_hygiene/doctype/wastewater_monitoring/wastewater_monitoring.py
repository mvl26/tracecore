"""Wastewater Monitoring — đợt quan trắc nước thải (FEAT-095; FR-M15-10, .1, FR-M15-11, FR-M15-13; BRU-ENV-003..006).
Luật ở ``environmental_hygiene.wastewater``."""

from frappe.model.document import Document

from tracecore.environmental_hygiene import wastewater


class WastewaterMonitoring(Document):
	def validate(self):
		wastewater.validate(self)

	def before_submit(self):
		wastewater.before_submit(self)

	def on_submit(self):
		wastewater.on_submit(self)

	def on_cancel(self):
		wastewater.on_cancel(self)
