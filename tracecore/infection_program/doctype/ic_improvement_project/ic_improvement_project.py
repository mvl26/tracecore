"""IC Improvement Project — dự án cải tiến chất lượng / đề tài nghiên cứu KSNK (FEAT-072; FR-M11-12; A-149 Q2).

Trạng thái theo PDCA; Hoàn thành cần ngày kết thúc và tóm tắt kết quả. Không ghi sổ, không xóa (dùng Hủy).
"""

from frappe.model.document import Document

from tracecore.infection_program import improvement


class ICImprovementProject(Document):
	def validate(self):
		improvement.validate(self)
