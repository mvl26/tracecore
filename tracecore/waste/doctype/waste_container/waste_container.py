"""Waste Container: túi/thùng chất thải mã `CT-` (FEAT-047, FR-M10-01.5, BRU-ID-006); chỉ dịch vụ `waste.collection` tạo và đổi."""

import frappe
from frappe import _
from frappe.model.document import Document


class WasteContainer(Document):
	def before_insert(self):
		if not self.flags.tc_waste:
			frappe.throw(_("Waste containers are created by a waste collection."))
