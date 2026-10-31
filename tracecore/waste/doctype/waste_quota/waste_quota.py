"""Waste Quota: định mức chất thải theo khoa - loại, có ngày hiệu lực (FEAT-050, FR-M10-08, A-63)."""

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import audit


class WasteQuota(Document):
	def validate(self):
		if frappe.db.exists(
			"Waste Quota",
			{
				"department": self.department,
				"waste_type": self.waste_type,
				"effective_from": self.effective_from,
				"name": ["!=", self.name or ""],
			},
		):
			frappe.throw(_("This department and waste type already have a quota from that date."))

	def on_trash(self):
		audit.block_delete(self, "on_trash")
