from frappe.model.document import Document

from tracecore.occupational_safety import immunization


class StaffImmunization(Document):
	def validate(self):
		immunization.validate(self)
