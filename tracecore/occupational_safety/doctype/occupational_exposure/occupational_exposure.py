from frappe.model.document import Document

from tracecore.occupational_safety import exposure


class OccupationalExposure(Document):
	def validate(self):
		exposure.validate(self)

	def after_insert(self):
		exposure.after_insert(self)
