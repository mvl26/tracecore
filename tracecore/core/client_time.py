"""Thời điểm nghiệp vụ từ client (`client_ts`): ISO 8601 bắt buộc có offset, lưu UTC (ADR-003).

`check_skew` chặn `client_ts` lệch giờ server quá `tc_client_ts_max_skew_seconds` (site config, mặc định 300 s) ở
những nơi `client_ts` quyết định dữ liệu in ra (ngày trong Cycle ID, hạn dùng, kiểm lô chỉ thị khi sinh online).
"""

import math
from datetime import datetime, timezone

import frappe
from frappe import _
from frappe.utils import cint

DEFAULT_MAX_SKEW_SECONDS = 300


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


def utc_now():
	"""Giờ server UTC không múi giờ (cùng dạng `parse_client_ts` trả)."""
	return datetime.now(timezone.utc).replace(tzinfo=None)


def max_skew_seconds():
	return cint(frappe.conf.get("tc_client_ts_max_skew_seconds")) or DEFAULT_MAX_SKEW_SECONDS


def check_skew(client_ts):
	"""`client_ts` (UTC không múi giờ) lệch giờ server quá `max_skew_seconds()` → ClientTimestampError (400)."""
	seconds = abs((client_ts - utc_now()).total_seconds())
	if seconds > max_skew_seconds():
		raise ClientTimestampError(
			_(
				"The station clock differs from the server clock by {0} minutes. Call R10 to check the station time (NTP), then try again."
			).format(math.ceil(seconds / 60))
		)
