"""Tiện ích chung cho RPC tracecore.v1: định dạng lỗi nghiệp vụ, kiểm role/trạm, giờ server."""

from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.data import get_system_timezone

AGENT_ROLE = "TC Agent"


def rejection(code, title, reason, action):
	"""Lỗi nghiệp vụ cho trạm: kết quả → lý do → hành động (design.md §6)."""
	return {"ok": False, "error": {"code": code, "title": title, "reason": reason, "action": action}}


def server_time():
	"""Giờ server ISO 8601 có offset theo múi giờ hệ thống."""
	return now_datetime().replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat()


def require_role(role):
	# Không dùng frappe.only_for: hàm đó bỏ qua kiểm tra khi chạy test
	if role not in frappe.get_roles():
		raise frappe.PermissionError(_("This method requires the role {0}.").format(role))


def require_station(station):
	if not station or not frappe.db.exists("Zone Station", {"name": station, "is_zone": 0}):
		frappe.throw(_("Station {0} does not exist.").format(station))
