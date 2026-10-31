"""Waste Handover: phiếu bàn giao chất thải (FEAT-049, UC-36, FR-M10-04, A-62); luật ở `waste.handover`.

Sửa phiếu đã ghi sổ = Hủy rồi lập phiếu mới; không xóa (FR-M10-04.6).
"""

from frappe.model.document import Document

from tracecore.core import audit
from tracecore.waste import handover


class WasteHandover(Document):
	def validate(self):
		handover.validate(self)

	def before_submit(self):
		handover.before_submit(self)

	def on_submit(self):
		handover.on_submit(self)

	def on_cancel(self):
		handover.on_cancel(self)

	def on_trash(self):
		audit.block_delete(self, "on_trash")
