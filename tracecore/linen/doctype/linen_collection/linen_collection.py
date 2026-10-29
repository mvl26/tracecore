"""Linen Collection: phiếu thu gom đồ vải theo khoa (FEAT-033, UC-16, FR-M3-01; architecture §5.3 DT-LINENCOL, A-49).

Controller chỉ chuyển cho `linen.collection`. Sửa phiếu đã ghi sổ = Hủy rồi Sửa đổi; không xóa (hook `on_trash`).
"""

from frappe.model.document import Document

from tracecore.linen import collection


class LinenCollection(Document):
	def validate(self):
		collection.validate(self)
