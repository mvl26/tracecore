"""Wastewater Permit — giấy phép môi trường có phiên bản (FEAT-095; FR-M15-08, .1; BRU-ENV-004). Luật ở
``environmental_hygiene.wastewater``."""

from frappe.model.document import Document

from tracecore.environmental_hygiene import wastewater


class WastewaterPermit(Document):
	def autoname(self):
		wastewater.permit_autoname(self)

	def validate(self):
		wastewater.validate_permit(self)

	def before_update_after_submit(self):
		wastewater.guard_locked(self)

	def on_submit(self):
		wastewater.on_approve(self)
