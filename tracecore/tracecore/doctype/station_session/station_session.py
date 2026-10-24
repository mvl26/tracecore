import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, now_datetime


class StationSession(Document):
	def before_insert(self):
		self.started_at = self.started_at or now_datetime()
		self.last_activity_at = self.last_activity_at or self.started_at
		self.absolute_expires_at = self.absolute_expires_at or add_to_date(self.started_at, hours=8)
		self.is_open = 1

	def validate(self):
		if self.ended_at:
			self.is_open = 0
		elif not self.is_open:
			frappe.throw(_("A closed station session requires an end timestamp."))

	def on_trash(self):
		frappe.throw(_("Station Session {0} cannot be deleted.").format(self.name))
