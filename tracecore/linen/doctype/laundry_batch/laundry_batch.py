"""Laundry Batch: lô giặt theo kg (FEAT-034, UC-17, FR-M3-03, FR-M3-04; architecture §5.3 DT-LAUNDRY, A-50).

Lô do `linen.laundry` tạo và hoàn tất; controller chỉ giữ quy ước tên. Ghi sổ rồi Hủy, không xóa (hook `on_trash`).
"""

from frappe.model.document import Document


class LaundryBatch(Document):
	pass
