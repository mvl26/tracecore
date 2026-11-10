"""Sampling Plan — kế hoạch lấy mẫu môi trường (FEAT-070; FR-M15-05). Luật ở ``environmental_hygiene.plans``."""

from frappe.model.document import Document

from tracecore.environmental_hygiene import plans


class SamplingPlan(Document):
	def validate(self):
		plans.validate(self)
