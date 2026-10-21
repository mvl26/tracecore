"""RPC tracecore.v1.zone.* — chức năng trạm được phép theo khu, cho form Zone Station trên Desk (FEAT-002 E3)."""

import frappe

from tracecore.core import zones


@frappe.whitelist(methods=["GET", "POST"])
def allowed_steps(zone):
	"""Các bước T1-T8 được phép đặt cho trạm thuộc khu `zone`; `zone` không phải khu thì ``[]``.

	Chỉ đọc. Bảng chức năng nằm ở ``core.zones.STEPS_BY_ZONE_TYPE``, JS không giữ bản sao.
	"""
	frappe.has_permission("Zone Station", "read", throw=True)
	if not zone or not isinstance(zone, str):
		return []
	row = frappe.db.get_value("Zone Station", {"name": zone, "is_zone": 1}, "zone_type")
	return list(zones.allowed_steps(row)) if row else []
