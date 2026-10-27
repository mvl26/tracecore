import frappe
from frappe import _
from frappe.model.document import Document


class ImportBatch(Document):
	"""Log một lần import danh mục (A-41); chỉ `core.importer` tạo và cập nhật, không xóa."""

	def validate(self):
		if not self.flags.tc_import:
			frappe.throw(_("Import batches are written by the catalog import only."))

	def on_trash(self):
		frappe.throw(_("Import batches cannot be deleted."))
