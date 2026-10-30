"""RPC tracecore.v1.code_range.* — cấp dải Cycle ID offline cho trạm T4 (FEAT-009, A-40 Q4)."""

import frappe

from tracecore.core import code_range
from tracecore.core.client_time import parse_client_ts, to_system_time
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import PACKING_ROLES, current_station_session, require_any_role, station_session


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*PACKING_ROLES)
@idempotent
def allocate(station, client_ts=None, token=None):
	"""Mọi dải còn hạn của trạm hôm nay (cấp thêm khi còn < 20 %): ``{"ok": true, "ranges": [...]}``."""
	require_any_role(*PACKING_ROLES)
	on = to_system_time(parse_client_ts(client_ts)).date()
	session = current_station_session()
	ranges = code_range.ensure(station, on, session.name if session else None)
	return {"ok": True, "ranges": [{**row, "expires_at": str(row["expires_at"])} for row in ranges]}
