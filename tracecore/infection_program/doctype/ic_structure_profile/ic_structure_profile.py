"""IC Structure Profile — bộ tiêu chí cơ cấu KSNK có phiên bản (FEAT-094; FR-M11-01.8; A-138 a, A-143).

Luật vòng đời ở ``infection_program.structure_profile``.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import strip_html

from tracecore.infection_program import structure_profile


class ICStructureProfile(Document):
	def before_insert(self):
		structure_profile.before_insert(self)

	def validate(self):
		structure_profile.validate(self)

	@frappe.whitelist()
	def approve(self):
		"""Nút Approve trên form (R01): Nháp → Đã duyệt; lỗi nghiệp vụ trả về để form hiện inline."""
		try:
			structure_profile.approve(self.name)
		except frappe.PermissionError:
			raise
		except frappe.ValidationError as error:
			frappe.clear_messages()
			return {
				"ok": False,
				"error": {
					"title": _("Not approved"),
					"reason": strip_html(str(error)),
					"action": _("Correct the draft and approve again."),
				},
			}
		return {"ok": True}
