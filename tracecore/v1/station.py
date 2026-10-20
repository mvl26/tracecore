"""RPC tracecore.v1.station.* — cấu hình trạm cho Station Agent (role TC Agent, API key)."""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import print as core_print
from tracecore.v1._common import (
	AGENT_ROLE,
	require_agent_for,
	require_role,
	require_station,
	station_inactive_block,
)

PERIPHERAL_FIELDS = ["peripheral_type", "model", "connection", "host", "port", "serial_port", "baud_rate"]


def _station_row(station):
	row = frappe.db.get_value(
		"Zone Station",
		station,
		["name", "zone_station_name", "parent_zone", "zone_type", "station_step", "is_active"],
		as_dict=True,
	)
	return {
		"name": row.name,
		"label": _(row.zone_station_name),
		"zone": row.parent_zone,
		"zone_type": row.zone_type,
		"step": row.station_step,
		"is_active": cint(row.is_active),
	}


def _active_peripherals(station):
	return frappe.get_all(
		"Station Peripheral",
		filters={"parent": station, "parenttype": "Zone Station", "is_active": 1},
		fields=PERIPHERAL_FIELDS,
		order_by="idx",
	)


@frappe.whitelist(methods=["POST"])
def config(station, client_ts=None):
	"""Cấu hình trạm cho agent: thông tin trạm, máy in hoạt động (D11) và thiết bị ngoại vi hoạt động (FEAT-002).

	Agent chỉ in tới máy in có trong danh sách này. Trạm không hoạt động → body từ chối STATION_INACTIVE (409).
	Không dùng @idempotent: chỉ đọc, giống `agent.heartbeat`.
	"""
	require_role(AGENT_ROLE)
	require_station(station, allow_inactive=True)
	require_agent_for(station)
	info = _station_row(station)
	if not info["is_active"]:
		block = station_inactive_block(station)
		if getattr(frappe.local, "request", None):
			frappe.local.response["http_status_code"] = block.http_status
		return {"ok": False, "error": block.as_dict()}
	return {
		"station": info,
		"printers": core_print.station_printers(station),
		"peripherals": _active_peripherals(station),
	}
