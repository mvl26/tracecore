"""Audit Log: nhật ký append-only (ADR-008). Chỉ tạo mới; sửa/xóa luôn bị chặn."""

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core.audit import AuditLogImmutableError


class AuditLog(Document):
	def before_save(self):
		if not self.is_new():
			raise AuditLogImmutableError(_("Audit Log entries cannot be modified."))

	def on_trash(self):
		raise AuditLogImmutableError(_("Audit Log entries cannot be deleted."))


def on_doctype_update():
	frappe.db.add_index("Audit Log", ["ref_doctype", "ref_name", "timestamp"])
	frappe.db.add_index("Audit Log", ["user", "timestamp"])
	frappe.db.add_index("Audit Log", ["station", "timestamp"])
