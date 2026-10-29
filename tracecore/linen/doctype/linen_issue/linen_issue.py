"""Linen Issue: cấp phát / cấp mới / hủy đồ vải theo khoa (FEAT-035, UC-18, FR-M3-05, FR-M3-06; architecture §5.3
DT-LINENISS, A-50).

Controller chỉ chuyển cho `linen.issue`. Sửa phiếu đã ghi sổ = Hủy rồi Sửa đổi; không xóa (hook `on_trash`).
"""

from frappe.model.document import Document

from tracecore.linen import issue


class LinenIssue(Document):
	def validate(self):
		issue.validate(self)

	def before_submit(self):
		issue.before_submit(self)
