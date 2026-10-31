"""Test hằng ngày cấu hình theo từng viện (A-70): ghi mặc định "Bắt buộc tất cả máy tiệt khuẩn" nếu viện chưa chọn, mở máy
đang khóa vì `Daily Test` mà không còn thuộc diện (máy rửa, thiết bị khác)."""

from tracecore.equipment import daily_test


def execute():
	daily_test.ensure_settings()
	daily_test.release_stale_locks()
