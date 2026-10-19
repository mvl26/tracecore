"""Thời điểm nghiệp vụ từ client (`client_ts`): ISO 8601 bắt buộc có offset, lưu UTC (ADR-003)."""

from datetime import datetime, timezone

import frappe
from frappe import _


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
