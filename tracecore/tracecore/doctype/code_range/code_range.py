from frappe.model.document import Document

from tracecore.core import code_range


class CodeRange(Document):
	"""Dải Cycle ID offline của một trạm trong một ngày; `core.code_range` cấp, R10 được sửa số và hạn (A-75)."""

	def validate(self):
		code_range.validate_edit(self)

	def on_update(self):
		code_range.report_overlap(self)
