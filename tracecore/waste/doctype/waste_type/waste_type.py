"""Waste Type: loại chất thải theo nhóm TT 20/2021 (FEAT-047, FR-M10-01, A-59 W6-W8); luật ở `waste.types`."""

from frappe.model.document import Document

from tracecore.waste import types


class WasteType(Document):
	def validate(self):
		types.validate(self)
