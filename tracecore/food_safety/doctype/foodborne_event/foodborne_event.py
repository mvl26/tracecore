from frappe.model.document import Document

from tracecore.food_safety import events


class FoodborneEvent(Document):
	def validate(self):
		events.validate(self)

	def before_submit(self):
		events.before_submit(self)

	def on_submit(self):
		events.on_submit(self)
