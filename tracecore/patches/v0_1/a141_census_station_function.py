"""A-141 (FEAT-062): chức năng trạm CENSUS (mẫu số ngày, đợt thiết bị trên PDA của khoa) cho site đang chạy.

`ensure_station_catalog` chỉ chèn chức năng còn thiếu và thêm chức năng mới vào loại vùng đã có (Department); bản ghi
R10 đã sửa giữ nguyên.
"""

from tracecore.setup import seed


def execute():
	seed.ensure_station_catalog()
