"""RPC phản hồi / báo lỗi phần mềm từ trạm (FEAT-013, FR-M9-15, A-55 D7).

Lớp mỏng trên `tracecore.ui.feedback`: phiên thẻ nhân viên (`@station_session`, token trong body POST) xác định người
gửi; mọi vai trò TraceCore gửi được. Ghi nên dùng ``@idempotent``: kiosk gửi lại cùng khóa không tạo Issue thứ hai.
"""

import frappe

from tracecore.core.idempotency import idempotent
from tracecore.ui import feedback as feedback_service
from tracecore.v1._common import current_station_session, station_session

FEEDBACK_ROLES = (*(f"TC R{n:02d}" for n in range(1, 11)), "System Manager")


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*FEEDBACK_ROLES)
@idempotent
def create(station, kind, description, screenshot=None, context=None, client_ts=None, token=None):
	"""``{"ok": true, "issue"}``; từ chối → ``{"ok": false, "error"}`` (FEEDBACK_INVALID, SCREENSHOT_INVALID 422,
	FEEDBACK_RATE_LIMIT 429)."""
	session = current_station_session()
	issue = feedback_service.create(
		kind,
		description,
		station,
		session.employee,
		session.user,
		screenshot=screenshot,
		context=context,
	)
	return {"ok": True, "issue": issue}
