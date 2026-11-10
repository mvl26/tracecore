"""Report Export Profile — hồ sơ ánh xạ cột xuất báo cáo (FEAT-064; FR-M13-12, 12.1; BRU-RPT-002; A-147 Q1).

Mỗi hồ sơ gắn một loại xuất (`core.exporter`): chọn cột của loại xuất, đặt tiêu đề theo mẫu cơ quan quản lý yêu cầu,
định dạng Excel/CSV. Cột mã người bệnh rõ hoặc họ tên bị chặn (UC-49 E3).
"""

from frappe.model.document import Document

from tracecore.core import exporter


class ReportExportProfile(Document):
	def validate(self):
		exporter.validate_profile(self)
