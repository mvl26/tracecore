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
CONSUMABLE_FIELDS = (
	"item",
	"role",
	"is_required",
	"uom",
	"qty_per_load",
	"qty_per_pack",
	"qty_per_kg",
	"unit_price",
)
CHILD_FIELDS = {
	"consumables": ("item", "role", "is_required", "uom", "qty_per_load", "qty_per_pack"),
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


# --- Áp vật tư sang chương trình cùng loại (A-111 D4, FR-M5-02.7) ----------------------------------------------


def _kind_key(program):
	"""(loại chương trình, loại máy) của `program`: chỉ áp vật tư giữa chương trình cùng khóa này."""
	row = frappe.db.get_value("Process Program", program, ["program_kind", "equipment"], as_dict=True)
	if not row:
		frappe.throw(_("Process program {0} does not exist.").format(program or "-"))
	return (row.program_kind or "Regular", frappe.db.get_value("Equipment", row.equipment, "equipment_type"))


def consumable_targets(program: str) -> list[dict]:
	"""Chương trình đang dùng cùng loại chương trình và cùng loại máy với `program` (trừ chính nó), kèm cờ gợi ý.

	``suggested`` = 1 khi cùng tên chương trình hoặc cùng loại test đầu ngày: thường là cùng một chương trình trên máy khác.
	"""
	kind, equipment_type = _kind_key(program)
	source = frappe.db.get_value(
		"Process Program", program, ["program_name", "daily_test_type"], as_dict=True
	)
	rows = frappe.db.sql(
		"""select p.name, p.program_name, p.equipment, e.equipment_name, p.daily_test_type
		from `tabProcess Program` p join `tabEquipment` e on e.name = p.equipment
		where p.is_active = 1 and p.name != %s and ifnull(p.program_kind, 'Regular') = %s
			and e.equipment_type = %s and e.status != 'Retired'
		order by p.equipment asc, p.program_name asc""",
		(program, kind, equipment_type),
		as_dict=True,
	)
	return [
		{
			"program": row.name,
			"program_name": row.program_name,
			"equipment": row.equipment,
			"equipment_name": row.equipment_name,
			"suggested": int(
				row.program_name == source.program_name
				or bool(source.daily_test_type and row.daily_test_type == source.daily_test_type)
			),
		}
		for row in rows
	]


def copy_consumables(program: str, targets: list[str], ignore_permissions: bool = False) -> list[str]:
	"""Thay bảng vật tư của các chương trình `targets` bằng bảng của `program`; trả tên các chương trình đã áp.

	Đích phải là chương trình đang dùng cùng loại chương trình và cùng loại máy, khác chương trình nguồn; sai một đích thì
	không áp đích nào (tầng RPC hoàn tác về savepoint). Sửa nguồn sau đó không tự lan sang đích.
	"""
	allowed = {row["program"] for row in consumable_targets(program)}
	wrong = [target for target in targets or [] if target not in allowed]
	if wrong or not targets:
		frappe.throw(
			_(
				"Consumables of program {0} can only be applied to other active programs of the same kind on the same type of machine: {1}."
			).format(  # fmt: skip
				program, ", ".join(wrong) or "-"
			)
		)
	rows = [
		{field: row.get(field) for field in CONSUMABLE_FIELDS}
		for row in frappe.get_doc("Process Program", program).consumables
	]
	for target in targets:
		doc = frappe.get_doc("Process Program", target)
		doc.set("consumables", [dict(row) for row in rows])
		doc.save(ignore_permissions=ignore_permissions)
	return list(targets)
