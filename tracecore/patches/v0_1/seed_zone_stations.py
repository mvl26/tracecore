"""Tạo khu-trạm mặc định còn thiếu (ZONE-DIRTY/CLEAN/STERILE, TR-001..007) sau khi bỏ fixtures Zone Station.

Site đã cài có sẵn các bản ghi (từ fixtures cũ) nên patch không làm gì; không bao giờ ghi đè bản ghi đã có.
"""

from tracecore.setup.seed import ensure_zone_stations


def execute():
	ensure_zone_stations()
