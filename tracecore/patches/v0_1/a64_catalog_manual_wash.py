"""A-64: site đã chạy bản đầu của patch cấu hình trạm bổ sung chức năng MANUAL_WASH (chỉ thêm, không ghi đè)."""

from tracecore.setup.seed import ensure_station_catalog


def execute():
	ensure_station_catalog()
