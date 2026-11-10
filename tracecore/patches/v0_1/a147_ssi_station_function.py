"""A-147 (FEAT-064): chức năng trạm SSI_FOLLOWUP (theo dõi NKVM sau ra viện trên PDA) và nhóm phẫu thuật khởi
tạo cho site đang chạy.

`ensure_station_catalog` chỉ chèn chức năng còn thiếu và thêm vào loại vùng Department đã có; bản ghi R10 đã sửa giữ
nguyên. Nhóm phẫu thuật chỉ chèn mã còn thiếu, chưa bật giám sát (NFR-MAINT-04).
"""

from tracecore.hai_surveillance import ssi_seed
from tracecore.setup import seed


def execute():
	seed.ensure_station_catalog()
	ssi_seed.ensure_seed()
