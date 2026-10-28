"""Notification Rule: người nhận bổ sung, kênh và mức khẩn theo loại sự kiện (FEAT-010, FR-M9-10, ADR-014)."""

import frappe
from frappe import _
from frappe.model.document import Document

REQUIRED = {"Role": "role", "User": "user"}


class NotificationRule(Document):
	def validate(self):
		self.event_code = (self.event_code or "").strip().upper()
		for row in self.recipients:
			field = REQUIRED.get(row.recipient_type)
			if field and not row.get(field):
				frappe.throw(_("Row {0}: choose a {1}.").format(row.idx, _(field.title())))
		if self.urgency == "Urgent" and not self.escalate_after_min:
			self.escalate_after_min = 15
