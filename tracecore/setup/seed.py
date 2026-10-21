"""Khung khu-trạm mặc định (FEAT-002): 3 khu ZONE-DIRTY/CLEAN/STERILE và 7 trạm TR-001..007.

Không dùng fixtures: `bench migrate` nhập lại fixtures với force (xóa rồi chèn lại bản ghi, cả bảng con) nên trạm R10 đã
tắt sẽ bật lại và thiết bị ngoại vi mất. Khung chỉ được tạo NẾU CHƯA CÓ (`after_install` và patch cho site đã cài),
không bao giờ ghi đè bản ghi đã có, giống `label_templates.ensure_sample_templates`.
"""

import frappe

DEFAULT_ZONES = (
	{"name": "ZONE-DIRTY", "zone_station_name": "Dirty zone", "zone_type": "Dirty"},
	{"name": "ZONE-CLEAN", "zone_station_name": "Clean zone", "zone_type": "Clean"},
	{"name": "ZONE-STERILE", "zone_station_name": "Sterile zone", "zone_type": "Sterile"},
)

DEFAULT_STATIONS = (
	{
		"name": "TR-001",
		"zone_station_name": "T1 Receiving",
		"parent_zone": "ZONE-DIRTY",
		"station_step": "T1",
	},
	{"name": "TR-002", "zone_station_name": "T2 Washing", "parent_zone": "ZONE-DIRTY", "station_step": "T2"},
	{"name": "TR-003", "zone_station_name": "T3 Assembly", "parent_zone": "ZONE-CLEAN", "station_step": "T3"},
	{"name": "TR-004", "zone_station_name": "T4 Packing", "parent_zone": "ZONE-CLEAN", "station_step": "T4"},
	{
		"name": "TR-005",
		"zone_station_name": "T5 Sterilization",
		"parent_zone": "ZONE-CLEAN",
		"station_step": "T5",
	},
	{
		"name": "TR-006",
		"zone_station_name": "T6 Sterile storage",
		"parent_zone": "ZONE-STERILE",
		"station_step": "T6",
	},
	{
		"name": "TR-007",
		"zone_station_name": "T7 Issuing",
		"parent_zone": "ZONE-STERILE",
		"station_step": "T7",
	},
)


def ensure_zone_stations() -> list[str]:
	"""Tạo khu rồi trạm mặc định còn thiếu (đang hoạt động); trả tên các bản ghi vừa tạo theo thứ tự tạo.

	Bản ghi đã có (kể cả bản R10 đã sửa hoặc đã tắt) giữ nguyên. Trạm lấy loại khu từ khu cha khi validate và ghi
	Code Registry (prefix TR) trong `after_insert`.
	"""
	created = []
	for is_zone, rows in ((1, DEFAULT_ZONES), (0, DEFAULT_STATIONS)):
		for row in rows:
			if frappe.db.exists("Zone Station", row["name"]):
				continue
			values = {key: value for key, value in row.items() if key != "name"}
			frappe.get_doc({"doctype": "Zone Station", "is_zone": is_zone, "is_active": 1, **values}).insert(
				ignore_permissions=True, set_name=row["name"]
			)
			created.append(row["name"])
	return created
