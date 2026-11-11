"""Chủng đa kháng chưa xử lý (FEAT-067; FR-M14-04; SCR-59; A-136 Q5).

"Chưa xử lý" = chủng đa kháng còn thông báo ``MDRO_DETECTED`` trong ứng dụng chưa đọc của bất kỳ người nhận nào. Đọc
thông báo (hoặc FEAT-068 tạo lệnh cách ly rồi ``notification.resolve``) là đã xử lý.
"""

import frappe

from tracecore.microbiology import isolates

SCREEN_SLUG = "vi-sinh"
IN_APP = "In App"


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: số chủng đa kháng có thông báo chưa đọc của chính người dùng."""
	rows = frappe.get_all(
		"Notification Delivery",
		filters={
			"recipient": user,
			"channel": IN_APP,
			"status": "Sent",
			"event_code": isolates.MDRO_EVENT,
			"ref_doctype": isolates.DOCTYPE,
		},
		pluck="ref_name",
	)
	return {SCREEN_SLUG: len(set(rows))}


def pending():
	"""Chủng đa kháng chưa xử lý: ``{"count", "isolates": [tên], "first_sent": giờ gửi sớm nhất}``."""
	rows = frappe.get_all(
		"Notification Delivery",
		filters={
			"channel": IN_APP,
			"status": "Sent",
			"event_code": isolates.MDRO_EVENT,
			"ref_doctype": isolates.DOCTYPE,
		},
		fields=["ref_name", "sent_at"],
		order_by="sent_at asc",
	)
	names = list(dict.fromkeys(row.ref_name for row in rows))
	return {"count": len(names), "isolates": names, "first_sent": rows[0].sent_at if rows else None}
