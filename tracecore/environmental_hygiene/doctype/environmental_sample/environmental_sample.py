"""Environmental Sample — mẫu môi trường (FEAT-070; FR-M15-03, FR-M15-04; BRU-ENV-002, BRU-ENV-003). Luật ở
``environmental_hygiene.samples``."""

from frappe.model.document import Document

from tracecore.environmental_hygiene import samples


class EnvironmentalSample(Document):
	def validate(self):
		samples.validate(self)

	def before_submit(self):
		samples.before_submit(self)

	def on_submit(self):
		samples.on_submit(self)

	def on_cancel(self):
		samples.on_cancel(self)
