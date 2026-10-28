"""RPC tracecore.v1.notification.* — Trung tâm thông báo SCR-42 (FEAT-010, FR-M9-10, UC-38).

Desk (WEB) dùng phiên Frappe của người dùng; trạm/PDA dùng token phiên thẻ nhân viên (``station_summary``, chỉ đọc,
không tính là hoạt động nên không kéo dài phiên). Quy tắc nằm ở `core.notification`.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import notification, station_auth
from tracecore.core.errors import BlockedError


def _names(names):
	"""`names` là danh sách mã thông báo, gửi dạng JSON hoặc mảng; sai kiểu thì báo lỗi validation."""
	try:
		names = frappe.parse_json(names) if isinstance(names, str) else names
	except ValueError:
		names = None
	if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
		frappe.throw(_("names must be a list of notification IDs."), frappe.ValidationError)
	return names


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to open TraceCore."), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def inbox(only_unread=0, event_code=None, surface=None, start=0, limit=50):
	"""Thông báo của người dùng hiện tại, mới nhất trước. Trả ``{"ok", "rows", "unread", "has_more"}``."""
	_require_login()
	return {"ok": True, **notification.inbox(only_unread, event_code, surface, start, limit)}


@frappe.whitelist(methods=["GET"])
def unread_count(surface=None):
	_require_login()
	return {"ok": True, "unread": notification.unread_count(surface)}


@frappe.whitelist(methods=["POST"])
def mark_read(names):
	"""Đánh dấu Đã đọc; `names` là danh sách mã thông báo (JSON). Bỏ qua thông báo của người khác."""
	_require_login()
	names = _names(names)
	return {"ok": True, "changed": notification.mark_read(names), "unread": notification.unread_count()}


@frappe.whitelist(methods=["POST"])
def mark_all_read(event_code=None):
	_require_login()
	return {
		"ok": True,
		"changed": notification.mark_all_read(event_code),
		"unread": notification.unread_count(),
	}


def _as_station(token, call, touch=False):
	"""Chạy `call` với tư cách người đăng nhập bằng thẻ; đọc thì không tính là hoạt động (không kéo dài phiên)."""
	try:
		with station_auth.as_session_user(token, touch=touch):
			return call()
	except BlockedError as error:
		if getattr(frappe.local, "request", None):
			frappe.local.response["http_status_code"] = error.block.http_status
		return {"ok": False, "error": error.block.as_dict()}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def station_summary(token=None):
	"""Chuông trạm/PDA: số chưa đọc và thông báo khẩn mới nhất của người đang đăng nhập bằng thẻ."""

	def call():
		rows = notification.inbox(only_unread=1, limit=50)["rows"]
		urgent = next(
			(
				{key: row[key] for key in ("name", "subject", "link", "sent_at")}
				for row in rows
				if row["urgency"] == "Urgent"
			),
			None,
		)
		return {"ok": True, "unread": cint(notification.unread_count()), "urgent": urgent}

	return _as_station(token, call)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def station_inbox(token=None, limit=20):
	"""Danh sách thông báo chưa đọc trên màn trạm/PDA (SCR-42), mới nhất trước."""
	return _as_station(
		token, lambda: {"ok": True, **notification.inbox(only_unread=1, surface=None, limit=limit)}
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def station_mark_read(token=None, names=None):
	"""Đánh dấu Đã đọc trên màn trạm/PDA; tính là hoạt động của phiên."""
	names = _names(names)
	return _as_station(
		token,
		lambda: {"ok": True, "changed": notification.mark_read(names), "unread": notification.unread_count()},
		touch=True,
	)
