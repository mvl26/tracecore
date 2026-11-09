"""IC Committee — quyết định thành lập Hội đồng KSNK (FEAT-057; FR-M11-02; BRU-ICP-002; UC-40 A3).

Kiểm tra nghiệp vụ nằm ở validate hook ``infection_program.structure.check`` (đăng ký trong hooks). Controller chỉ
báo cảnh báo thiếu khối đại diện khi ghi sổ (FR-M11-02.2).
"""

from frappe.model.document import Document

from tracecore.infection_program import structure


class ICCommittee(Document):
	def on_submit(self):
		structure.warn_missing_representatives(self)
