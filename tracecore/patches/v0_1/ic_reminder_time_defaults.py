"""Site đang chạy: giờ nhắc mẫu số / gói dự phòng bị Frappe điền bằng giờ lúc tạo IC Program Settings → về 10:00.

Chỉ sửa ô trống hoặc có phần lẻ giây (tự điền); giờ bệnh viện đã chọn giữ nguyên.
"""

from tracecore.infection_program.settings_defaults import ensure_reminder_times


def execute():
	ensure_reminder_times()
