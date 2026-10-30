"""Environment Log: một lần đo nhiệt độ, độ ẩm, áp suất chênh của khu (FEAT-008, FR-M9-04, A-55).

Chứng từ Nháp → Ghi sổ → Hủy; nhập tay trên Desk (R02-R06) hoặc cảm biến qua `tracecore.v1.env.log`. Kiểm số liệu,
so ngưỡng khu và cảnh báo khi Ghi sổ ở `admin_reports.environment`. Không xóa.
"""

from frappe.model.document import Document

from tracecore.admin_reports import environment
from tracecore.core import audit


class EnvironmentLog(Document):
	def validate(self):
		environment.validate_reading(self)

	def on_submit(self):
		environment.alert_out_of_range(self)

	def on_trash(self):
		audit.block_delete(self, "on_trash")
