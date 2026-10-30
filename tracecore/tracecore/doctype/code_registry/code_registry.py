"""Code Registry: sổ đăng ký mã đã cấp — không sửa, không xóa, không cấp lại (FR-M9-07.1)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

IMMUTABLE_FIELDS = ("code", "prefix", "ref_doctype", "ref_name", "issued_on")


class CodeRegistry(Document):
	def validate(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if before and any(str(before.get(f) or "") != str(self.get(f) or "") for f in IMMUTABLE_FIELDS):
			frappe.throw(_("An issued code cannot be changed."))
		if self.status == "Disabled" and not self.disabled_on:
			self.disabled_on = now_datetime()

	def on_trash(self):
		frappe.throw(_("An issued code cannot be deleted; disable it instead."))
