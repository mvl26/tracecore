"""A-137 (FEAT-071): chức năng trạm EXPOSURE (báo phơi nhiễm trên PDA) cho site đang chạy.

`ensure_station_catalog` chỉ chèn chức năng còn thiếu và thêm chức năng mới vào loại vùng đã có (Department); bản ghi
R10 đã sửa giữ nguyên. Trạm PDA cụ thể của khoa do R10 gán chức năng trên Desk.
"""

from tracecore.setup import seed


def execute():
	seed.ensure_station_catalog()
