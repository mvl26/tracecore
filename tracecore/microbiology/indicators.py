"""Chỉ số M14 cho bảng chỉ số KSNK M9 qua hook `tracecore_ic_indicators` (FEAT-068; FR-M14-07; UC-52 bước 6; QĐ 38).

Hàm nhận kỳ ``YYYY-MM`` và khoa (rỗng = toàn viện), trả (tử số, mẫu số, cỡ mẫu). Chỉ số liệu, không có người bệnh.
"""

from frappe.utils import get_last_day, getdate

from tracecore.microbiology import isolation

COVERAGE_KEY = "isolation_room_coverage"


def register():
	return {COVERAGE_KEY: isolation_room_coverage}


def isolation_room_coverage(period, department=None):
	"""Khoa lâm sàng có ≥ 1 phòng cách ly đạt (đã kiểm tra trước cuối kỳ) / khoa lâm sàng."""
	result = isolation.coverage(get_last_day(getdate(f"{period}-01")), department)
	return result["covered"], result["total"], result["total"]
