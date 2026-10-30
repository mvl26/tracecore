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


@frappe.whitelist(methods=["GET", "POST"])
def next_zone(zone):
	"""Khu kế tiếp của `zone` theo chiều Bẩn → Sạch → Vô khuẩn, để form Thiết bị gợi ý khu cửa ra.

	Trả ``""`` khi `zone` là khu cuối, không phải khu hoặc loại khu nằm ngoài luồng. Nhiều khu cùng loại thì lấy
	khu đầu theo tên. Chỉ đọc; chiều đi nằm ở ``core.zones.ZONE_FLOW``, JS không giữ bản sao.
	"""
	frappe.has_permission("Zone Station", "read", throw=True)
	if not zone or not isinstance(zone, str):
		return ""
	zone_type = frappe.db.get_value("Zone Station", {"name": zone, "is_zone": 1}, "zone_type")
	next_type = zones.next_zone_type(zone_type)
	if not next_type:
		return ""
	return (
		frappe.db.get_value(
			"Zone Station", {"is_zone": 1, "zone_type": next_type}, "name", order_by="name asc"
		)
		or ""
	)
