import frappe
from frappe import _
from frappe.model.document import Document


class SyncConflict(Document):
	"""Xung đột khi phát lại offline (A-40); chỉ `core.sync` tạo và đóng, không xóa."""

	def validate(self):
		if not self.is_new() and not self.flags.tc_sync:
			frappe.throw(_("A sync conflict is closed with Resolve, not edited by hand."))

	def on_trash(self):
		frappe.throw(_("Sync conflicts cannot be deleted."))
