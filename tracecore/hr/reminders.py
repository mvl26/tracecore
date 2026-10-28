"""Nhắc hạn 60/30/7 ngày và khi hết hạn (FEAT-036, FR-M4-01.4, FR-M4-02.1, BRU-HR-002).

Mỗi bản ghi nhớ mức đã nhắc (60, 30, 7 hoặc -1 = đã hết hạn); chỉ nhắc khi tới mức sau, nên việc hằng ngày bị lỡ vài
ngày vẫn nhắc đúng mức hiện tại một lần và đổi ngày hạn thì đặt lại mức về 0.
"""

from frappe.utils import cint

THRESHOLDS = (60, 30, 7)
EXPIRED = -1
RANK = {0: 0, 60: 1, 30: 2, 7: 3, EXPIRED: 4}


def level_for(days_left: int) -> int:
	"""Mức nhắc ứng với số ngày còn lại: 60/30/7, -1 khi đã quá hạn, 0 khi còn xa."""
	if days_left < 0:
		return EXPIRED
	for threshold in sorted(THRESHOLDS):
		if days_left <= threshold:
			return threshold
	return 0


def is_due(level: int, sent) -> bool:
	"""Có phải nhắc không: `level` là mức hiện tại, `sent` là mức đã nhắc gần nhất (rỗng = chưa nhắc)."""
	return level != 0 and RANK[level] > RANK.get(cint(sent), 0)


def run_daily():
	"""Việc hằng ngày 00:00: chứng chỉ hết hạn, nhắc chứng chỉ và hồ sơ sức khỏe sắp hết hạn."""
	from tracecore.hr import certificates, employees

	certificates.run_daily()
	employees.remind_health_records()
