"""Isolation Room — phòng cách ly theo khoa (FEAT-068; FR-M14-07; A-146 Q2). Luật ở ``microbiology.isolation``."""

from frappe.model.document import Document

from tracecore.microbiology import isolation


class IsolationRoom(Document):
	def validate(self):
		isolation.validate_room(self)
