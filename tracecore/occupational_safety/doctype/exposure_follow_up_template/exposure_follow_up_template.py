from frappe.model.document import Document

from tracecore.occupational_safety import config


class ExposureFollowupTemplate(Document):
	def before_insert(self):
		config.before_insert_template(self)

	def validate(self):
		config.validate_template(self)
