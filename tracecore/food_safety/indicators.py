"""Chỉ số M17 đẩy sang bảng chỉ số KSNK M9 qua hook `tracecore_ic_indicators` (FEAT-073; FR-M17-02; QĐ 38).

Mỗi hàm nhận kỳ ``YYYY-MM`` và khoa (rỗng = toàn viện), trả (tử số, mẫu số, cỡ mẫu); chỉ số liệu, không có tên.
"""

from frappe.utils import get_last_day, getdate

from tracecore.food_safety import handlers


def register():
	return {"food_handler_health_valid": handler_health_valid}


def handler_health_valid(period, department=None):
	"""Người chế biến có kết luận Đủ và còn hạn khám tại cuối kỳ / tổng người chế biến."""
	end = get_last_day(getdate(f"{period}-01"))
	rows = handlers.latest(end, department)
	valid = sum(1 for row in rows if row["fit_for_work"] == handlers.FIT and row["state"] != handlers.OVERDUE)
	return valid, len(rows), len(rows)
