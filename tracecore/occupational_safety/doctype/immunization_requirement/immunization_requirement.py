from frappe.model.document import Document

from tracecore.occupational_safety import config


class ImmunizationRequirement(Document):
	def validate(self):
		config.validate_requirement(self)
