"""RPC hướng dẫn theo trạm (FEAT-013, FR-M9-15, A-55 D6).

Chỉ đọc, không cần phiên thẻ: người chưa quét thẻ cũng xem được cách đăng nhập. Kiosk cache bài cuối để xem khi offline.
"""

import frappe

from tracecore.ui import station_help
from tracecore.v1._common import require_station


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get(station):
	"""``{"ok", "key", "article"}``; `article` = ``{"name", "key", "title", "steps", "modified"}`` hoặc None."""
	require_station(station, allow_inactive=True)
	article = station_help.article_for(station)
	return {"ok": True, "key": station_help.station_key(station), "article": article}
