"""RPC hướng dẫn theo trạm (FEAT-013, FR-M9-15, A-56 D6).

Chỉ đọc, không cần phiên thẻ: người chưa quét thẻ cũng xem được cách đăng nhập. Kiosk cache bài cuối để xem khi offline.
"""

import frappe

from tracecore.ui import station_help
from tracecore.v1._common import require_station


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get(station=None):
	"""``{"ok", "key", "article"}``; `article` = ``{"name", "key", "title", "steps", "modified"}`` hoặc None.

	Địa chỉ trạm thiếu ``?station=`` vẫn trả bài General: bài này chỉ cách mở đúng địa chỉ trạm (ticket 03/11/2026).
	"""
	if not station:
		key = station_help.GENERAL
		return {"ok": True, "key": key, "article": station_help.article_for_key(key)}
	require_station(station, allow_inactive=True)
	article = station_help.article_for(station)
	return {"ok": True, "key": station_help.station_key(station), "article": article}
