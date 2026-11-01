"""Chương trình xử lý của máy: danh sách đang dùng và sao chép giữa máy cùng model (FR-M5-02, UC-21 A2, FEAT-038).

Hàm thuần trên DB; bọc whitelist và kiểm quyền ở tầng RPC. Không import phân hệ nghiệp vụ khác.
"""

import frappe
from frappe import _


class ProgramModelMismatchError(frappe.ValidationError):
	"""Sao chép chương trình sang máy khác hãng hoặc model."""


class EquipmentRetiredError(frappe.ValidationError):
	"""Máy đích đã ngừng sử dụng, không nhận chương trình mới."""


LIST_FIELDS = (
	"program_code",
	"program_name",
	"temperature",
	"pressure",
	"duration_min",
	"requires_bi",
	"norm_status",
)
SCALAR_FIELDS = (
	"temperature",
	"pressure",
	"duration_min",
	"chemical",
	"requires_bi",
	"program_kind",
	"kwh_per_cycle",
	"water_l_per_cycle",
	"steam_kg_per_cycle",
	"use_default_norms",
)
CHILD_FIELDS = {
	"consumables": ("item", "uom", "qty_per_load", "qty_per_pack"),
	"compatible_pack_types": ("pack_type",),
	"parameters": ("parameter_name", "unit", "min_value", "max_value", "required"),
}


def active_programs(equipment: str) -> list[dict]:
	"""Chương trình đang dùng (``is_active = 1``) của đúng máy `equipment`, theo tên chương trình.

	Máy đã ngừng sử dụng (``Retired``) trả danh sách rỗng: FEAT-021/022 không chọn được chương trình của máy đó.
	"""
	if frappe.db.get_value("Equipment", equipment, "status") == "Retired":
		return []
	rows = frappe.get_all(
		"Process Program",
		filters={"equipment": equipment, "is_active": 1},
		fields=["name", *LIST_FIELDS],
		order_by="program_name asc, program_code asc",
	)
	pack_types = {row.name: [] for row in rows}
	if rows:
		for child in frappe.get_all(
			"Program Compatible Pack Type",
			filters={"parent": ("in", list(pack_types)), "parenttype": "Process Program"},
			fields=["parent", "pack_type"],
			order_by="idx asc",
		):
			pack_types[child.parent].append(child.pack_type)
	return [
		{**{field: row[field] for field in LIST_FIELDS}, "compatible_pack_types": pack_types[row.name]}
		for row in rows
	]


def _model_key(equipment):
	row = frappe.db.get_value("Equipment", equipment, ["manufacturer", "model", "status"], as_dict=True)
	if not row:
		frappe.throw(_("Equipment {0} does not exist.").format(equipment))
	return row, ((row.manufacturer or "").strip().casefold(), (row.model or "").strip().casefold())


def copy_program(
	program: str,
	equipment: str,
	new_code: str,
	keep_default_norms: bool = False,
	ignore_permissions: bool = False,
) -> str:
	"""Sao chép `program` sang máy `equipment` cùng hãng và model với mã mới; trả tên chương trình mới.

	Mặc định bản sao KHÔNG mang cờ ``use_default_norms`` (chỉ R10/System Manager đặt cờ này, Q7) và insert có kiểm
	quyền. Tầng RPC quyết định sau khi kiểm role: ``keep_default_norms`` giữ cờ của chương trình nguồn,
	``ignore_permissions`` cho role không có quyền tạo trực tiếp (R02).
	Khi được phép giữ cờ và nguồn là ``Default``, bản sao giữ trạng thái này qua ``flags.tc_copied_norm_status`` mà
	``norms.norm_status`` đọc khi chưa có bản lưu trước. Nếu không được giữ cờ (đặc biệt RPC của R02), bản sao dùng
	các số đã sao chép nhưng ``use_default_norms = 0`` và được tính lại như chương trình thường. Dòng ``Equipment Type
	Norm`` của loại máy đã mất thì việc sao chép có giữ cờ bị từ chối như khi lưu chính chương trình nguồn.
	"""
	source = frappe.get_doc("Process Program", program)
	if source.equipment == equipment:
		frappe.throw(_("Choose a different equipment to copy program {0} to.").format(program))
	source_key = _model_key(source.equipment)[1]
	target, target_key = _model_key(equipment)
	if source_key != target_key:
		frappe.throw(
			_("Program {0} can only be copied to equipment of the same manufacturer and model.").format(
				program
			),
			ProgramModelMismatchError,
		)
	if target.status == "Retired":
		frappe.throw(
			_("Equipment {0} is retired and cannot get a new process program.").format(equipment),
			EquipmentRetiredError,
		)

	values = {
		"doctype": "Process Program",
		"program_code": new_code,
		"program_name": source.program_name,
		"equipment": equipment,
		"is_active": 1,
	}
	values.update({field: source.get(field) for field in SCALAR_FIELDS})
	for table, fields in CHILD_FIELDS.items():
		values[table] = [{field: row.get(field) for field in fields} for row in source.get(table)]
	copy = frappe.get_doc(values)
	if not keep_default_norms:
		copy.use_default_norms = 0
	elif source.norm_status == "Default":
		# bản sao không đủ hơn bản nguồn: số mặc định đã điền vào nguồn vẫn là mặc định, cờ chỉ phản chiếu nguồn
		copy.flags.tc_copied_norm_status = "Default"
	return copy.insert(ignore_permissions=ignore_permissions).name
