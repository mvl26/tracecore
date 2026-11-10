from frappe.model.document import Document

from tracecore.food_safety import education


class ICEducationSession(Document):
	def validate(self):
		education.validate(self)
