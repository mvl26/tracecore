"""Linen Type: loại đồ vải (FEAT-033, FR-M3-02; architecture §5.3 DT-LINENTYPE, A-49).

Controller chỉ chuyển cho `linen.types`. Không xóa (hook `on_trash` của Audit Log); ngừng dùng bằng `is_active`.
"""

from frappe.model.document import Document

from tracecore.linen import types


class LinenType(Document):
	def before_naming(self):
		types.before_naming(self)

	def validate(self):
		types.validate(self)
