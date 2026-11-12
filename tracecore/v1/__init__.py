"""RPC namespace ``tracecore.v1.<domain>.<action>`` (ADR-001). Logic nghiệp vụ nằm ở ``tracecore.core``."""

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.data import get_system_timezone

import tracecore
from tracecore.core import zones
from tracecore.v1._common import server_time, station_inactive_block

AGENT_HEARTBEAT_CACHE = "tc_agent_heartbeat"


def _station_info(station):
	row = frappe.db.get_value(
		"Zone Station",
		{"name": station, "is_zone": 0},
		["name", "zone_station_name", "station_no", "zone_type", "is_active"],
		as_dict=True,
	)
	if not row:
		return None, {
			"code": "STATION_NOT_FOUND",
			"title": _("Station not configured"),
			"reason": _("Station {0} does not exist.").format(station),
			"action": _("Check the kiosk address or call R10."),
		}
	if not row.is_active:
		block = station_inactive_block(station)
		return None, {
			"code": block.code,
			"title": block.title,
			"reason": block.reason,
			"action": block.action,
		}
	functions = zones.station_functions(row.name)
	return {
		"name": row.name,
		"label": _(row.zone_station_name),
		"functions": functions,
		"station_no": cint(row.station_no),
		"screens": zones.station_screen_tabs(functions),
		"gate_labels": zones.gate_labels(),
		"gate_stations": zones.gate_stations(),
		"zone_type": row.zone_type,
		"zone_color": zones.zone_color_class(row.zone_type),
	}, None


def _station_by_number(station_no):
	"""NAV-07: kiosk mở /app/station/<số trạm>; đổi Số trạm thành mã trạm (đúng một trạm đang dùng)."""
	number = cint(station_no)
	names = (
		frappe.get_all(
			"Zone Station",
			filters={"is_zone": 0, "is_active": 1, "station_no": number},
			pluck="name",
			order_by="name asc",
			# kiosk chưa quét thẻ có thể không đọc được Zone Station; chỉ trả mã trạm
			ignore_permissions=True,
		)
		if number > 0
		else []
	)
	if len(names) == 1:
		return names[0], None
	if not names:
		return None, {
			"code": "STATION_NOT_FOUND",
			"title": _("Station not configured"),
			"reason": _("No active station has number {0}.").format(station_no),
			"action": _("Check the kiosk address or call R10."),
		}
	return None, {
		"code": "STATION_NUMBER_DUPLICATE",
		"title": _("Station not configured"),
		"reason": _("Station number {0} is used by several stations: {1}.").format(number, ", ".join(names)),
		"action": _(
			"Ask R10 to give each station its own number, or open the address with the station code."
		),
	}


@frappe.whitelist()
def ping(station=None, station_no=None):
	"""Bắt tay của kiosk/agent: phiên bản, site, múi giờ, giờ server, thông tin trạm, trạng thái agent.

	``station_no`` (NAV-07): kiosk mở theo Số trạm; mã trạm ``station`` có thì thắng.
	"""
	error = None
	if not station and station_no not in (None, ""):
		station, error = _station_by_number(station_no)
	info, error = _station_info(station) if station else (None, error)
	agent = frappe.cache.hget(AGENT_HEARTBEAT_CACHE, station) if station else None
	return {
		"app": "tracecore",
		"version": tracecore.__version__,
		"site": frappe.local.site,
		"time_zone": get_system_timezone(),
		"server_time": server_time(),
		"station": info,
		"station_error": error,
		"agent": agent,
	}
