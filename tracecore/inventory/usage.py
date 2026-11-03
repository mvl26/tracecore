"""Vật tư dùng ở đâu (A-112 D9, D12; FR-M6-02.4, FR-M6-07).

"Dùng cho" của vật tư không khai trên Item mà suy từ chương trình đang có vật tư đó: công đoạn theo loại máy (Rửa: máy
rửa siêu âm và lô rửa tay; Khử khuẩn: máy rửa khử khuẩn; Tiệt khuẩn: máy tiệt khuẩn), chương trình loại Test là công đoạn
Test kèm loại test đầu ngày. Báo cáo sử dụng vật tư nhóm theo cùng cách suy này.
"""

import frappe
from frappe.utils import flt

WASHING, DISINFECTION, STERILIZATION, TEST = "Washing", "Disinfection", "Sterilization", "Test"
STAGES = (WASHING, DISINFECTION, STERILIZATION, TEST)
EQUIPMENT_STAGES = {
	"Ultrasonic Cleaner": WASHING,
	"Washer-Disinfector": DISINFECTION,
	"Steam Sterilizer": STERILIZATION,
	"Plasma Sterilizer": STERILIZATION,
}
TEST_PROGRAM = "Test"
MANUAL_WASH = ("Manual", "Ultrasonic")  # Wash Batch.batch_type không chạy máy rửa khử khuẩn


def stage(equipment_type, program_kind=None, batch_type=None):
	"""Công đoạn của một lần chạy hoặc một chương trình; máy ngoài bốn công đoạn (máy giặt, máy hàn…) → None."""
	if program_kind == TEST_PROGRAM:
		return TEST
	if batch_type in MANUAL_WASH:
		return WASHING
	return EQUIPMENT_STAGES.get(equipment_type)


def programs_using(item):
	"""Chương trình có `item` trong bảng vật tư: máy, công đoạn, loại test, vai trò, định mức; đang dùng trước."""
	rows = frappe.get_all(
		"Program Consumable",
		filters={"item": item, "parenttype": "Process Program"},
		fields=["parent", "role", "is_required", "uom", "qty_per_load", "qty_per_pack", "qty_per_kg"],
	)
	result = []
	for row in rows:
		program = frappe.db.get_value(
			"Process Program",
			row.parent,
			["name", "program_name", "equipment", "is_active", "program_kind", "daily_test_type"],
			as_dict=True,
		)
		if not program:
			continue
		equipment = (
			frappe.db.get_value(
				"Equipment", program.equipment, ["equipment_name", "equipment_type"], as_dict=True
			)
			or frappe._dict()
		)
		result.append(
			{
				"program": program.name,
				"program_name": program.program_name,
				"is_active": program.is_active,
				"equipment": program.equipment,
				"equipment_name": equipment.equipment_name,
				"equipment_type": equipment.equipment_type,
				"stage": stage(equipment.equipment_type, program.program_kind),
				"test_type": program.daily_test_type or None,
				"role": row.role or None,
				"is_required": row.is_required,
				"uom": row.uom,
				"qty_per_load": flt(row.qty_per_load),
				"qty_per_pack": flt(row.qty_per_pack),
				"qty_per_kg": flt(row.qty_per_kg),
			}
		)
	result.sort(
		key=lambda row: (not row["is_active"], row["equipment_name"] or "", row["program_name"] or "")
	)
	return result
