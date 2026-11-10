"""Environment Risk Level — mức nguy cơ vùng vệ sinh do R01 cấu hình (FEAT-070; BRU-ENV-001; A-148 a)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class EnvironmentRiskLevel(Document):
	def validate(self):
		if cint(self.min_audits_per_month) < 0:
			frappe.throw(_("Minimum audits per month cannot be negative."))
