"""Khung vùng-trạm mặc định (FEAT-002, A-64): danh mục chức năng, loại vùng, 4 khu và 8 trạm TR-001..008.

Không dùng fixtures: `bench migrate` nhập lại fixtures với force (xóa rồi chèn lại bản ghi, cả bảng con) nên trạm R10 đã
tắt sẽ bật lại và thiết bị ngoại vi mất. Khung chỉ được tạo NẾU CHƯA CÓ (`after_install` và patch cho site đã cài),
không bao giờ ghi đè bản ghi đã có, giống `label_templates.ensure_sample_templates`.
"""

import frappe

# (mã, tên, thứ tự quy trình, cổng, màn, bắt buộc trong chuỗi). Thứ tự và cổng cố định (FR-M2-00.4, BRU-FLOW-003).
DEFAULT_FUNCTIONS = (
	("RECEIVE", "Receiving", 10, "T1", "receive", 1),
	("WASH_LOAD", "Washer loading", 20, None, "wash", 1),
	("WASH_UNLOAD", "Washer unloading", 25, "T2", "wash", 1),
	("ASSEMBLE", "Assembly", 30, "T3", "assembly", 1),
	("PACK", "Packing", 40, "T4", "pack", 1),
	("STERI_LOAD", "Sterilizer loading", 50, None, "sterilize", 1),
	("STERI_UNLOAD", "Sterilizer unloading", 55, "T5", "sterilize", 1),
	("PUTAWAY", "Sterile storage", 60, None, "storage", 1),
	("ISSUE", "Issuing", 70, None, "issue", 1),
	("USE", "Usage", 80, None, "usage", 1),
	("LINEN", "Linen", 100, None, "linen", 0),
	("WASTE", "Waste collection", 110, None, "waste", 0),
)

# (loại vùng, màu, thứ tự qua máy hai cửa, chức năng được phép)
DEFAULT_ZONE_TYPES = (
	("Dirty", "dirty", 10, ("RECEIVE", "WASH_LOAD", "WASH_UNLOAD")),
	("Clean", "clean", 20, ("WASH_UNLOAD", "ASSEMBLE", "PACK", "STERI_LOAD", "STERI_UNLOAD")),
	("Sterile", "sterile", 30, ("STERI_UNLOAD", "PUTAWAY", "ISSUE")),
	("Department", "dept", 0, ("USE",)),
	("Linen", "web", 0, ("LINEN",)),
	("Waste", "waste", 0, ("WASTE",)),
)

DEFAULT_ZONES = (
	{"name": "ZONE-DIRTY", "zone_station_name": "Dirty zone", "zone_type": "Dirty"},
	{"name": "ZONE-CLEAN", "zone_station_name": "Clean zone", "zone_type": "Clean"},
	{"name": "ZONE-STERILE", "zone_station_name": "Sterile zone", "zone_type": "Sterile"},
	{"name": "ZONE-DEPT", "zone_station_name": "Department zone", "zone_type": "Department"},
)

DEFAULT_STATIONS = (
	{
		"name": "TR-001",
		"zone_station_name": "T1 Receiving",
		"parent_zone": "ZONE-DIRTY",
		"station_no": 1,
		"functions": ("RECEIVE",),
	},
	{
		"name": "TR-002",
		"zone_station_name": "T2 Washing",
		"parent_zone": "ZONE-DIRTY",
		"station_no": 2,
		"functions": ("WASH_LOAD", "WASH_UNLOAD"),
	},
	{
		"name": "TR-003",
		"zone_station_name": "T3 Assembly",
		"parent_zone": "ZONE-CLEAN",
		"station_no": 3,
		"functions": ("ASSEMBLE",),
	},
	{
		"name": "TR-004",
		"zone_station_name": "T4 Packing",
		"parent_zone": "ZONE-CLEAN",
		"station_no": 4,
		"functions": ("PACK",),
	},
	{
		"name": "TR-005",
		"zone_station_name": "T5 Sterilization",
		"parent_zone": "ZONE-CLEAN",
		"station_no": 5,
		"functions": ("STERI_LOAD", "STERI_UNLOAD"),
	},
	{
		"name": "TR-006",
		"zone_station_name": "T6 Sterile storage",
		"parent_zone": "ZONE-STERILE",
		"station_no": 6,
		"functions": ("PUTAWAY",),
	},
	{
		"name": "TR-007",
		"zone_station_name": "T7 Issuing",
		"parent_zone": "ZONE-STERILE",
		"station_no": 7,
		"functions": ("ISSUE",),
	},
	{
		"name": "TR-008",
		"zone_station_name": "T8 Usage",
		"parent_zone": "ZONE-DEPT",
		"station_no": 8,
		"functions": ("USE",),
	},
)


def ensure_station_catalog() -> None:
	"""Tạo chức năng và loại vùng mặc định còn thiếu; bản ghi đã có (kể cả R10 đã sửa) giữ nguyên."""
	for code, label, order, gate, screen, required in DEFAULT_FUNCTIONS:
		if frappe.db.exists("Station Function", code):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Station Function",
				"function_code": code,
				"function_name": label,
				"process_order": order,
				"gate_step": gate,
				"screen_key": screen,
				"is_required": required,
				"is_system": 1,
				"is_active": 1,
			}
		)
		doc.flags.tc_seed = True
		doc.insert(ignore_permissions=True)
	for type_name, color, flow_order, functions in DEFAULT_ZONE_TYPES:
		if frappe.db.exists("Zone Type", type_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Zone Type",
				"type_name": type_name,
				"zone_color": color,
				"flow_order": flow_order,
				"functions": [{"station_function": function} for function in functions],
			}
		).insert(ignore_permissions=True)


def ensure_zone_stations() -> list[str]:
	"""Tạo danh mục, khu rồi trạm mặc định còn thiếu (đang hoạt động); trả tên các bản ghi vừa tạo theo thứ tự tạo.

	Bản ghi đã có (kể cả bản R10 đã sửa hoặc đã tắt) giữ nguyên. Trạm lấy loại khu từ khu cha khi validate và ghi
	Code Registry (prefix TR) trong `after_insert`.
	"""
	ensure_station_catalog()
	created = []
	for is_zone, rows in ((1, DEFAULT_ZONES), (0, DEFAULT_STATIONS)):
		for row in rows:
			if frappe.db.exists("Zone Station", row["name"]):
				continue
			values = {key: value for key, value in row.items() if key not in ("name", "functions")}
			values["functions"] = [{"station_function": function} for function in row.get("functions", ())]
			frappe.get_doc({"doctype": "Zone Station", "is_zone": is_zone, "is_active": 1, **values}).insert(
				ignore_permissions=True, set_name=row["name"]
			)
			created.append(row["name"])
	return created
