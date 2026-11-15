"""Thời điểm nghiệp vụ từ client (`client_ts`): ISO 8601 bắt buộc có offset, lưu UTC (ADR-003).

Thời điểm nghiệp vụ theo giờ máy khách (A-160): `check_skew` / `check_not_future` không từ chối nữa; `client_ts` lệch
giờ server (hoặc ở tương lai) quá `tc_client_ts_max_skew_seconds` (site config, mặc định 300 s) chỉ ghi Audit Log
`Override` lý do `CLIENT_CLOCK_SKEW` để R10 chỉnh giờ trạm.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, get_datetime
from frappe.utils.data import get_system_timezone

DEFAULT_MAX_SKEW_SECONDS = 300
SKEW_REASON = "CLIENT_CLOCK_SKEW"


class ClientTimestampError(frappe.ValidationError):
	http_status_code = 400


def parse_client_ts(value):
	"""Chuyển `client_ts` (vd ``2026-10-19T09:00:00+07:00``) thành datetime UTC không múi giờ."""
	if not value or not isinstance(value, str):
		raise ClientTimestampError(_("client_ts is required (ISO 8601 with offset)."))
	text = value.strip()
	if text.endswith("Z"):
		text = text[:-1] + "+00:00"
	try:
		parsed = datetime.fromisoformat(text)
	except ValueError:
		parsed = None
	if parsed is None or parsed.tzinfo is None:
		raise ClientTimestampError(_("client_ts must be ISO 8601 with a UTC offset: {0}").format(value))
	return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def to_system_time(utc_naive):
	"""Giờ UTC không múi giờ (dạng `parse_client_ts` trả; datetime hoặc chuỗi) → giờ hệ thống không múi giờ.

	Giờ hệ thống = múi giờ của site (``Asia/Ho_Chi_Minh``), cùng dạng ``now_datetime()``; dùng trước khi lấy NGÀY của
	một thời điểm từ client (vd ``step_gate.start_cycle(on=…)`` ghim phiên bản BOM theo ngày tiếp nhận). Cùng phép đổi
	với ``packing._system_time`` của T4 (D13).
	"""
	utc = get_datetime(utc_naive).replace(tzinfo=timezone.utc)
	return utc.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def utc_now():
	"""Giờ server UTC không múi giờ (cùng dạng `parse_client_ts` trả)."""
	return datetime.now(timezone.utc).replace(tzinfo=None)


def max_skew_seconds():
	return cint(frappe.conf.get("tc_client_ts_max_skew_seconds")) or DEFAULT_MAX_SKEW_SECONDS


def check_skew(client_ts):
	"""`client_ts` (UTC không múi giờ) lệch giờ server quá `max_skew_seconds()` → ghi Audit Log, vẫn nhận (A-160)."""
	_log_if_skewed(client_ts, abs((client_ts - utc_now()).total_seconds()))


def check_not_future(client_ts):
	"""Giao dịch offline phát lại (A-40): `client_ts` cũ không ghi gì; ở tương lai quá ngưỡng → ghi Audit Log, vẫn nhận."""
	_log_if_skewed(client_ts, (client_ts - utc_now()).total_seconds())


def _log_if_skewed(client_ts, seconds):
	if seconds <= max_skew_seconds():
		return
	from tracecore.core import audit

	audit.log(
		"Override",
		reason=SKEW_REASON,
		new={"client_ts": str(client_ts), "server_ts": str(utc_now()), "skew_seconds": round(seconds)},
		client_ts=client_ts,
	)
