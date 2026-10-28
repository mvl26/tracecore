"""Notification Delivery: một thông báo cho một người nhận trên một kênh (FEAT-010). Chỉ `core.notification` ghi."""

import frappe
from frappe import _
from frappe.model.document import Document


class NotificationDelivery(Document):
	def on_trash(self):
		frappe.throw(_("Notification records cannot be deleted."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_index("Notification Delivery", ["recipient", "channel", "status", "sent_at"])
	frappe.db.add_index("Notification Delivery", ["channel", "status", "attempts"])
