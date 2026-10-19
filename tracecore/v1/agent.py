"""RPC tracecore.v1.agent.* — Station Agent báo sống (role TC Agent, API key)."""

import frappe
from frappe.utils import cint

from tracecore.v1 import AGENT_HEARTBEAT_CACHE
from tracecore.v1._common import AGENT_ROLE, require_role, require_station, server_time


@frappe.whitelist(methods=["POST"])
def heartbeat(station, client_ts=None, agent_version=None, queue_depth=None, printer=None):
	"""Lưu trạng thái agent vào cache để kiosk thấy qua tracecore.v1.ping.

	Không dùng @idempotent: ghi đè cache vốn idempotent, tránh ~3.000 dòng Idempotency Key/trạm/ngày.
	"""
	require_role(AGENT_ROLE)
	require_station(station)
	now = server_time()
	frappe.cache.hset(
		AGENT_HEARTBEAT_CACHE,
		station,
		{
			"station": station,
			"agent_version": agent_version,
			"queue_depth": cint(queue_depth),
			"printer": printer,
			"client_ts": client_ts,
			"last_seen": now,
			"user": frappe.session.user,
		},
	)
	return {"ok": True, "server_time": now}
