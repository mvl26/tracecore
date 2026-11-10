from frappe.model.document import Document

from tracecore.food_safety import handlers


class FoodHandlerHealthCheck(Document):
	def validate(self):
		handlers.validate(self)
