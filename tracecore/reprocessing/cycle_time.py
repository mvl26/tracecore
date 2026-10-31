"""Thời lượng chu trình thực tế (giờ kết thúc trừ giờ bắt đầu) so với thời lượng chuẩn của chương trình (A-73).

Dùng chung cho lô rửa (T2) và mẻ tiệt khuẩn (T5). Chênh lệch quá `TOLERANCE_PCT` % so với chuẩn là bất thường: chỉ
cảnh báo, không chặn kết luận.
"""

import frappe
from frappe.utils import flt, get_datetime

TOLERANCE_PCT = 20


def assess(started_at, ended_at, standard_min):
	"""``{"actual_min", "standard_min", "deviation_pct", "abnormal", "direction"}`` hoặc None khi thiếu dữ liệu.

	None khi thiếu giờ, giờ kết thúc trước giờ bắt đầu, hay chương trình không có thời lượng chuẩn. `direction` là
	``short`` / ``long`` khi bất thường, ngược lại None. Phút làm tròn đến phút.
	"""
	standard = flt(standard_min)
	if not started_at or not ended_at or standard <= 0:
		return None
	seconds = (get_datetime(ended_at) - get_datetime(started_at)).total_seconds()
	if seconds < 0:
		return None
	actual = round(seconds / 60)
	deviation = round((seconds / 60 - standard) / standard * 100, 1)
	abnormal = abs(deviation) > TOLERANCE_PCT
	return {
		"actual_min": actual,
		"standard_min": standard,
		"deviation_pct": deviation,
		"abnormal": abnormal,
		"direction": ("short" if deviation < 0 else "long") if abnormal else None,
	}


def for_doc(doc):
	"""`assess` cho lô rửa hay mẻ tiệt khuẩn `doc` theo `duration_min` của chương trình."""
	standard = frappe.db.get_value("Process Program", doc.program, "duration_min")
	return assess(doc.started_at, doc.ended_at, standard)
