from frappe.model.document import Document

from tracecore.occupational_safety import config


class ImmunizationRequirement(Document):
	def before_insert(self):
		config.before_insert_requirement(self)

	def validate(self):
		config.validate_requirement(self)
