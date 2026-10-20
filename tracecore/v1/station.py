"""RPC tracecore.v1.station.* — cấu hình trạm cho Station Agent (role TC Agent, API key)."""

import frappe

from tracecore.core import print as core_print
from tracecore.v1._common import AGENT_ROLE, require_agent_for, require_role, require_station


@frappe.whitelist(methods=["POST"])
def config(station, client_ts=None):
	"""Cấu hình trạm cho agent: danh sách máy in hoạt động (D11); FEAT-002 bổ sung thiết bị ngoại vi khác.

	Agent chỉ in tới máy in có trong danh sách này. Không dùng @idempotent: chỉ đọc, giống `agent.heartbeat`.
	"""
	require_role(AGENT_ROLE)
	require_station(station)
	require_agent_for(station)
	return {"station": station, "printers": core_print.station_printers(station)}
