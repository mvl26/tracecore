"""Waste Treatment Vendor: đơn vị xử lý chất thải (FEAT-049, UC-36, FR-M10-05, .1, .3, BRU-WST-003); luật ở `waste.vendors`."""

from frappe.model.document import Document

from tracecore.core import audit
from tracecore.waste import vendors


class WasteTreatmentVendor(Document):
	def validate(self):
		vendors.validate(self)

	def on_trash(self):
		audit.block_delete(self, "on_trash")
