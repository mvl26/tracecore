"""Waste Collection: phiếu thu gom chất thải theo khoa (FEAT-047, UC-34, FR-M10-02, A-60); luật ở `waste.collection`.

Sửa phiếu đã ghi sổ = Hủy rồi Sửa đổi; không xóa (hook `on_trash`).
"""

from frappe.model.document import Document

from tracecore.waste import collection


class WasteCollection(Document):
	def validate(self):
		collection.validate(self)

	def on_submit(self):
		collection.on_submit(self)

	def on_cancel(self):
		collection.on_cancel(self)
