"""Quy tắc cột Tên cạnh cột mã (A-65): dùng chung cho script sinh JSON, patch backfill và test.

Chỉ chứa hằng số và hàm thuần để ``scripts/add_name_columns.py`` import được ngoài site.
"""

# Đích Link của app khác → trường tên có sẵn
EXTERNAL_NAME_FIELD = {
	"Employee": "employee_name",
	"Item": "item_name",
	"User": "full_name",
	"Supplier": "supplier_name",
	"Department": "department_name",
}

# Đích Link của TraceCore → trường tên (title_field), Set Unit lấy tên loại bộ qua ``set_type_name``
TRACECORE_NAME_FIELD = {
	"Equipment": "equipment_name",
	"Instrument": "instrument_name",
	"Instrument Set Type": "set_type_name",
	"Process Program": "program_name",
	"Zone Station": "zone_station_name",
	"Sterile Location": "location_name",
	"Waste Storage Location": "location_name",
	"Set Unit": "set_type_name",
	"TraceCore Error Code": "error_name",
	"Station Function": "function_name",
	"IC Indicator": "indicator_name",  # A-113 (FEAT-056)
	"IC Procedure Document": "title",  # A-133 (FEAT-058): bản thay thế trỏ bản cũ
	"Organism": "organism_name",  # FEAT-067 (A-136)
}

NAME_FIELD = {**EXTERNAL_NAME_FIELD, **TRACECORE_NAME_FIELD}

# Mã đã là tên: thêm cột sẽ lặp lại đúng giá trị
CODE_IS_NAME = frozenset(
	{
		"Batch",
		"Role",
		"Linen Type",
		"Cost Category",
		"Waste Type",
		"Waste Treatment Vendor",
		"DocType",
		"UOM",
		"Zone Type",
		"Designation",  # HRMS: name = designation_name (FEAT-071, Immunization Requirement)
		"Immunization Requirement",  # FEAT-071: autoname field:vaccine, mã chính là tên vaccine
	}
)

# FEAT-070 (A-148): vùng vệ sinh hiện tên khu; mức nguy cơ đặt tên theo `risk_name` nên mã chính là tên
TRACECORE_NAME_FIELD = {**TRACECORE_NAME_FIELD, "Environment Zone": "area_name"}
NAME_FIELD = {**NAME_FIELD, "Environment Zone": "area_name"}
CODE_IS_NAME = CODE_IS_NAME | {"Environment Risk Level"}

# Đích không có trường tên
NO_NAME_FIELD = frozenset({"Sterilization Load", "Pack", "Wash Batch", "Waste Container"})
# FEAT-063 (A-144): chủng vi sinh không có trường tên; dòng chủng của ca NKBV đã hiện loài, ngày lấy mẫu
NO_NAME_FIELD = NO_NAME_FIELD | {"Microbiology Isolate"}
# FEAT-069 (A-150): sự cố Incident CAPA và ca NKBV không có trường tên; dòng ca của ổ dịch đã hiện mã BN che, ngày khởi phát
NO_NAME_FIELD = NO_NAME_FIELD | {"Incident CAPA", "HAI Case"}

# Đã có sẵn cột tên (không fetch được hoặc đặt tên khác): giữ nguyên, không thêm trường trùng
EXISTING_NAME_COLUMN = {
	("Assembly Line", "instrument"): "instrument_name",
	("Loaner BOM Item", "instrument"): "instrument_name",
	("Dirty Receipt Item", "set_unit"): "set_name",
	("Issue Note Pack", "set_unit"): "set_name",
	("TraceCore Error Log", "error_code"): "error_name",
}
# FEAT-064 (A-147): ca phẫu thuật giám sát đã có `group_name` (fetch tên nhóm phẫu thuật) ngay sau mã nhóm
EXISTING_NAME_COLUMN[("Surgical Surveillance", "procedure_group")] = "group_name"
# FEAT-095 (A-153): điểm quan trắc nước thải hiện tên điểm; đợt quan trắc đã có `point_name` (fetch tên điểm quan trắc) ngay sau mã điểm
EXISTING_NAME_COLUMN[("Wastewater Monitoring", "wastewater_point")] = "point_name"
TRACECORE_NAME_FIELD = {**TRACECORE_NAME_FIELD, "Wastewater Point": "point_name"}
NAME_FIELD = {**NAME_FIELD, "Wastewater Point": "point_name"}

# Giới hạn Frappe Grid: tổng ``columns`` của các cột hiển thị tối đa 10
GRID_MAX_COLUMNS = 10


def name_fieldname(link_fieldname: str) -> str:
	return f"{link_fieldname}_name"


def skip_reason(doctype: str, link_field: str, target: str) -> str | None:
	"""Lý do bỏ qua (mã tiếng Anh) một Link in_list_view, ``None`` nếu phải có cột tên."""
	if (doctype, link_field) in EXISTING_NAME_COLUMN:
		return "existing column"
	if target in CODE_IS_NAME:
		return "code is name"
	if target in NO_NAME_FIELD:
		return "target has no name field"
	if target not in NAME_FIELD:
		return "no rule for target"
	return None


# Module Def của app (CLAUDE.md): phạm vi quét DocType TraceCore
MODULES = (
	"TraceCore",
	"Instrument",
	"Reprocessing",
	"Linen",
	"Equipment",
	"Inventory",
	"Costing",
	"Par",
	"Admin Reports",
	"Waste",
	"UI",
	# A-113 (FEAT-056): M11-M17
	"Infection Program",
	"Compliance Audit",
	"HAI Surveillance",
	"Microbiology",
	"Environmental Hygiene",
	"Occupational Safety",
	"Food Safety",
)
