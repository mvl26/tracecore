"""RPC tracecore.v1.zone.* — chức năng được phép theo vùng và chuỗi còn thiếu, cho form Zone Station (FEAT-002 E3, A-64)."""

import frappe

from tracecore.core import zones


@frappe.whitelist(methods=["GET", "POST"])
def allowed_functions(zone):
	"""Chức năng được phép đặt cho trạm thuộc vùng `zone`: ``[{"value", "label"}]``; `zone` không phải vùng thì ``[]``.

	Chỉ đọc. Quy tắc nằm ở ``Zone Type``, JS không giữ bản sao.
	"""
	frappe.has_permission("Zone Station", "read", throw=True)
	if not zone or not isinstance(zone, str):
		return []
	row = frappe.db.get_value("Zone Station", {"name": zone, "is_zone": 1}, "zone_type")
	if not row:
		return []
	return [
		{"value": function, "label": zones.function_label(function)} for function in zones.allowed_functions(row)
	]


@frappe.whitelist(methods=["GET", "POST"])
def chain_status():
	"""Chức năng bắt buộc chưa có trạm hoạt động: ``{"missing": [nhãn...]}``, để form cảnh báo bộ sẽ kẹt."""
	frappe.has_permission("Zone Station", "read", throw=True)
	return {"missing": [zones.function_label(function) for function in zones.missing_functions()]}


@frappe.whitelist(methods=["GET", "POST"])
def next_zone(zone):
	"""Vùng kế tiếp của `zone` theo ``Zone Type.flow_order``, để form Thiết bị gợi ý vùng cửa ra.

	Trả ``""`` khi `zone` là vùng cuối, không phải vùng hoặc loại vùng nằm ngoài luồng. Nhiều vùng cùng loại thì lấy
	vùng đầu theo tên. Chỉ đọc; JS không giữ bản sao.
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
