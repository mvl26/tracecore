"""A-145 (FEAT-065): chỉ tiêu QĐ 38 cho tự đánh giá năm và Notification Rule `IC_COUNCIL_REPORT` cho site đang chạy.

Cả hai chỉ chèn bản ghi còn thiếu; chỉ tiêu và Rule bệnh viện/R10 đã sửa giữ nguyên (NFR-MAINT-04).
"""

from tracecore.admin_reports import self_assessment_seed
from tracecore.core import notification


def execute():
	self_assessment_seed.ensure_seed()
	notification.ensure_default_rules()
