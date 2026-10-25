"""FEAT-027: site đã cài thêm khu ZONE-DEPT và trạm TR-008 (T8 quét sử dụng); không ghi đè bản ghi đã có."""

from tracecore.setup.seed import ensure_zone_stations


def execute():
	ensure_zone_stations()
