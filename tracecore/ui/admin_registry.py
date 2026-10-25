"""Navigation contracts for the independent TraceCore administration UI."""
# ruff: noqa: RUF001 -- Vietnamese clinical labels use the source document punctuation.

ROLES = {
	"R01": (
		"Trưởng khoa KSNK",
		"Phê duyệt, theo dõi và báo cáo",
		[
			"dashboard",
			"overrides",
			"recalls",
			"incidents",
			"costs",
			"equipment",
			"people",
			"sterilization-book",
		],
	),
	"R02": (
		"Giám sát CSSD",
		"Điều phối ca và xử lý ngoại lệ",
		["dashboard", "loads", "instruments", "set-types", "set-units", "competencies", "incidents", "sync"],
	),
	"R03": ("KTV khu bẩn", "Tiếp nhận và rửa–khử khuẩn", ["receipts", "wash-batches"]),
	"R04": (
		"KTV khu sạch",
		"Kiểm tra, lắp ráp và đóng gói",
		["assembly", "packs", "instruments", "overrides"],
	),
	"R05": ("KTV tiệt khuẩn", "Test ngày, vận hành và dỡ mẻ", ["equipment", "daily-tests", "loads"]),
	"R06": (
		"Kho vô khuẩn / cấp phát",
		"Vị trí, FEFO và cấp phát cho khoa",
		["putaways", "sterile-stock", "issues"],
	),
	"R07": (
		"Đồ vải & chất thải",
		"Thu gom, xử lý và bàn giao",
		[
			"linen-collections",
			"laundry",
			"linen-issues",
			"waste-collections",
			"waste-storage",
			"waste-handover",
		],
	),
	"R08": (
		"Khoa sử dụng",
		"Nhận, sử dụng và trả dụng cụ",
		["department-stock", "usage", "returns", "requests", "recalls", "linen-issues", "trace"],
	),
	"R09": (
		"Kế toán / Vật tư",
		"Vật tư, chi phí và giá thành",
		["items", "stock-entries", "cost-entries", "rates", "costs"],
	),
	"R10": (
		"Quản trị hệ thống",
		"Cấu hình, tài khoản và audit",
		["zones", "printers", "labels", "accounts", "audit", "instruments", "set-types", "set-units"],
	),
}

# Only these fields can leave the read API. Credentials and patient identifiers are absent.
# A missing DocType is unavailable, never represented by invented records.
SCREENS = {
	"instruments": (
		"Danh mục dụng cụ",
		"Instrument",
		["instrument_name", "instrument_group", "status", "version_no", "max_cycles", "image"],
	),
	"set-types": (
		"Loại bộ & BOM",
		"Instrument Set Type",
		["set_name", "set_type_name", "method", "current_bom_version", "shelf_life_days", "status"],
	),
	"set-units": (
		"Bộ dụng cụ / Set ID",
		"Set Unit",
		[
			"set_type",
			"status",
			"cycles_used",
			"max_cycles",
			"current_cycle_no",
			"cycle_bom_version",
			"department",
		],
	),
	"overrides": (
		"Ghi đè cơ số",
		"Par Override",
		["set_unit", "status", "reason", "extra_cycles", "valid_until"],
	),
	"recalls": ("Thu hồi", "Recall Order", ["status", "reason", "sterilization_load"]),
	"incidents": ("Sự cố / NC-CAPA", "Incident CAPA", ["status", "incident_type", "severity", "description"]),
	"equipment": (
		"Thiết bị & chương trình",
		"Equipment",
		["equipment_name", "equipment_type", "status", "zone_in", "zone_out", "serial_no"],
	),
	"people": ("Nhân sự & chứng chỉ", "Employee", ["employee_name", "department", "designation", "status"]),
	"competencies": (
		"Năng lực trạm",
		"Station Competency",
		["employee", "station_step", "valid_until", "status"],
	),
	"receipts": (
		"T1 · Tiếp nhận",
		"Dirty Receipt",
		["department", "handed_by", "received_by", "station", "docstatus"],
	),
	"wash-batches": (
		"T2 · Rửa–khử khuẩn",
		"Wash Batch",
		["equipment", "program", "status", "result", "station"],
	),
	"assembly": ("T3 · Kiểm tra–lắp ráp", "Assembly Record", ["set_unit", "status", "station", "docstatus"]),
	"packs": ("T4 · Đóng gói", "Pack", ["set_unit", "status", "method", "expiry", "packed_by_user"]),
	"loads": (
		"T5 / T5b · Mẻ tiệt khuẩn",
		"Sterilization Load",
		["equipment", "program", "status", "result", "docstatus"],
	),
	"daily-tests": ("Test hằng ngày", "Daily Test", ["equipment", "test_type", "result", "test_date"]),
	"putaways": ("T6 · Nhập kho", "Sterile Putaway", ["pack", "location", "station", "docstatus"]),
	"sterile-stock": ("Tồn kho vô khuẩn", "Pack", ["set_unit", "status", "expiry", "location"]),
	"issues": ("T7 · Cấp phát", "Issue Note", ["department", "status", "docstatus"]),
	"linen-collections": ("Thu gom đồ vải", "Linen Collection", ["department", "status", "total_weight"]),
	"laundry": ("Lô giặt", "Laundry Batch", ["equipment", "status", "total_weight"]),
	"linen-issues": ("Cấp phát đồ vải", "Linen Issue", ["department", "status", "docstatus"]),
	"waste-collections": (
		"Thu gom chất thải",
		"Waste Collection",
		["department", "waste_type", "weight", "status"],
	),
	"waste-storage": ("Kho lưu giữ chất thải", "Waste Storage", ["waste_type", "location", "status"]),
	"waste-handover": ("Bàn giao chất thải", "Waste Handover", ["contractor", "status", "docstatus"]),
	"department-stock": ("Bộ tại khoa & cơ số", None, []),
	"usage": ("T8 · Quét sử dụng", "Usage Record", ["pack", "department", "usage_date", "status"]),
	"returns": ("Gửi trả đồ bẩn", None, []),
	"requests": ("Đề nghị cấp", None, []),
	"trace": ("Truy xuất gói", None, []),
	"items": ("Danh mục vật tư", "Item", ["item_name", "item_group", "stock_uom", "disabled"]),
	"stock-entries": (
		"Nhập / xuất kho vật tư",
		"Stock Entry",
		["stock_entry_type", "posting_date", "total_incoming_value", "docstatus"],
	),
	"cost-entries": ("Chi phí", "Cost Entry", ["cost_type", "amount", "posting_date"]),
	"rates": ("Bảng định giá", "Cost Rate Version", ["status", "effective_from"]),
	"costs": (
		"Giá thành tái xử lý",
		"Cost Sheet",
		["set_unit", "sterilization_load", "total_cost", "status"],
	),
	"zones": (
		"Khu & trạm",
		"Zone Station",
		["zone_station_name", "station_step", "zone", "is_zone", "is_active"],
	),
	"printers": ("Máy in", "Printer", ["printer_name", "station", "is_active", "status"]),
	"labels": ("Mẫu nhãn", "Label Template", ["label_name", "label_object", "is_active"]),
	"accounts": ("Tài khoản & quyền", "User", ["full_name", "enabled", "user_type"]),
	"audit": (
		"Audit trail",
		"Audit Log",
		["timestamp", "user", "action", "ref_doctype", "ref_name", "reason"],
	),
	"sync": ("Xung đột đồng bộ", "Sync Conflict", ["station", "status", "ref_doctype", "ref_name"]),
	"sterilization-book": (
		"Sổ tiệt khuẩn điện tử",
		"Sterilization Load",
		["equipment", "program", "status", "result", "docstatus"],
	),
}
