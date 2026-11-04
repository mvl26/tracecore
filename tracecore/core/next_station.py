"""Trạm kế tiếp sau khi xong một bước (A-117, FR-M9-22): màn trạm hiện mã vạch của trạm kế để quét sang đó.

Chuỗi chức năng theo quy trình T1 → T8; bước cuối (sử dụng cho bệnh nhân, ``USE``) không có bước kế. Trạm kế là trạm đang
hoạt động có chức năng của bước kế: chính trạm hiện tại nếu nó cũng làm bước đó (như `assembly._next_station`), rồi trạm
cùng khu, rồi trạm khu khác (T2 → T3 đi qua máy hai cửa sang khu sạch). Chỉ chọn trạm, không đổi trạng thái nghiệp vụ nào.
"""

import frappe

from tracecore.core import zones

# chức năng của bước vừa xong -> chức năng của bước kế
NEXT_FUNCTION = {
	"RECEIVE": "WASH_LOAD",  # T1 -> T2
	"WASH_UNLOAD": "ASSEMBLE",  # T2 (dỡ lô, kết luận Đạt) -> T3
	"ASSEMBLE": "PACK",  # T3 -> T4
	"PACK": "STERI_LOAD",  # T4 -> T5
	"STERI_LOAD": "STERI_UNLOAD",  # T5 nạp mẻ -> T5b dỡ mẻ
	"STERI_UNLOAD": "PUTAWAY",  # T5b -> T6
	"PUTAWAY": "ISSUE",  # T6 -> T7
	"ISSUE": "USE",  # T7 -> T8
}


def _active(station):
	return bool(frappe.db.get_value("Zone Station", {"name": station, "is_zone": 0, "is_active": 1}, "name"))


def of(station, function):
	"""``{"station", "label", "function"}`` của trạm kế sau bước `function` làm ở `station`, hoặc None.

	None khi `function` là bước cuối hoặc không biết, hoặc chưa có trạm đang hoạt động nào có chức năng của bước kế.
	"""
	target = NEXT_FUNCTION.get(function)
	if not target or not station or not isinstance(station, str):
		return None
	chosen = None
	if _active(station) and zones.station_has_function(station, target):
		chosen = station
	else:
		zone = frappe.db.get_value("Zone Station", station, "parent_zone")
		candidates = zones.stations_with_function(target, zone=zone) or zones.stations_with_function(target)
		chosen = candidates[0] if candidates else None
	if not chosen:
		return None
	return {
		"station": chosen,
		"label": frappe.db.get_value("Zone Station", chosen, "zone_station_name") or chosen,
		"function": target,
	}
