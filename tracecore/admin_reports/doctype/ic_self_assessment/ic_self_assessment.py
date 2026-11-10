"""IC Self Assessment — tự đánh giá năm theo QĐ 38 (FEAT-065, FR-M9-29, FR-M9-29.1; A-145).

Mỗi năm một bản (`TDG-{year}`); R01 lập, điền dòng tự động qua ``admin_reports.self_assessment`` rồi ghi sổ.
"""

from frappe.model.document import Document

from tracecore.admin_reports import self_assessment


class ICSelfAssessment(Document):
	def validate(self):
		self_assessment.validate(self)
