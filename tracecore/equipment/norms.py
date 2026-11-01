"""Định mức tiêu hao của chương trình xử lý (FR-M5-02.1, FR-M5-02.4, BRU-EQP-003, FEAT-038 Q1/Q3).

Hàm thuần trên tài liệu và đọc DB; không import phân hệ nghiệp vụ khác.

* ``Complete``: phút > 0, kWh > 0, có ít nhất một dòng tiêu hao và, với loại máy dùng nước, nước > 0.
  Máy sấy không dùng nước và thường không dùng hóa chất nên không cần dòng tiêu hao (A-104).
* ``Default``: chưa đủ nhưng ``use_default_norms`` bật, loại máy có dòng ``Equipment Type Norm`` và sau khi
  điền số thiếu từ dòng đó thì đủ điều kiện trên (tiêu hao không bao giờ được mặc định). Chương trình đã
  ``Default`` ở lần lưu trước và còn đủ thì giữ ``Default`` để trạng thái không nhảy sang ``Complete``
  chỉ vì số mặc định đã được điền vào; bản sao mới của chương trình ``Default`` cũng vậy
  (``flags.tc_copied_norm_status``, đặt bởi ``programs.copy_program``).
* ``Missing``: còn lại. FEAT-046 không tính giá thành cho chương trình ``Missing``.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

WATER_EQUIPMENT_TYPES = ("Steam Sterilizer", "Washer-Disinfector", "Laundry Washer", "Ultrasonic Cleaner")
NO_CONSUMABLE_TYPES = ("Dryer",)
NORM_FIELDS = ("duration_min", "kwh_per_cycle", "water_l_per_cycle", "steam_kg_per_cycle")


def equipment_type_of(program):
	return frappe.db.get_value("Equipment", program.equipment, "equipment_type")


def default_norm(equipment_type):
	"""Định mức mặc định của loại máy, hoặc None khi chưa có dòng."""
	if not equipment_type:
		return None
	row = frappe.db.get_value("Equipment Type Norm", equipment_type, list(NORM_FIELDS), as_dict=True)
	if not row:
		return None
	return {field: flt(row.get(field)) for field in NORM_FIELDS}


def _meets(values, consumable_count, equipment_type):
	if flt(values.get("duration_min")) <= 0 or flt(values.get("kwh_per_cycle")) <= 0:
		return False
	if not consumable_count and equipment_type not in NO_CONSUMABLE_TYPES:
		return False
	if equipment_type in WATER_EQUIPMENT_TYPES and flt(values.get("water_l_per_cycle")) <= 0:
		return False
	return True


def _entered(program):
	return {field: flt(program.get(field)) for field in NORM_FIELDS}


def _filled(values, norm):
	return {field: (values[field] if values[field] > 0 else norm[field]) for field in NORM_FIELDS}


def norm_status(program) -> str:
	"""``Complete`` / ``Default`` / ``Missing`` của chương trình theo các giá trị hiện có (không ghi)."""
	equipment_type = equipment_type_of(program)
	count = len(program.get("consumables") or [])
	values = _entered(program)
	norm = default_norm(equipment_type) if cint(program.get("use_default_norms")) else None
	if _meets(values, count, equipment_type):
		before = program.get_doc_before_save() if hasattr(program, "get_doc_before_save") else None
		# chưa có bản lưu trước: bản sao của chương trình Default mang trạng thái nguồn qua cờ tài liệu
		previous = before.norm_status if before else program.flags.get("tc_copied_norm_status")
		if norm and previous == "Default":
			return "Default"
		return "Complete"
	if norm and _meets(_filled(values, norm), count, equipment_type):
		return "Default"
	return "Missing"


def apply_default(program) -> None:
	"""Điền số thiếu (<= 0) từ định mức mặc định của loại máy; không ghi đè số đã nhập."""
	norm = default_norm(equipment_type_of(program))
	if not norm:
		return
	for field, value in _filled(_entered(program), norm).items():
		if flt(program.get(field)) <= 0 and value > 0:
			program.set(field, value)


def _num(value):
	return f"{value:g}"


def range_warnings(program, equipment) -> list[str]:
	"""Cảnh báo khi nhiệt độ/áp suất của chương trình ngoài dải an toàn của máy; giá trị 0 là chưa đặt."""
	warnings = []
	temp = flt(program.get("temperature"))
	low, high = flt(equipment.get("safe_temp_min")), flt(equipment.get("safe_temp_max"))
	if temp > 0:
		if low > 0 and temp < low:
			warnings.append(
				_(
					"Program {0}: temperature {1} °C is below the safe minimum {2} °C of equipment {3}."
				).format(program.name or program.program_code, _num(temp), _num(low), program.equipment)
			)
		if high > 0 and temp > high:
			warnings.append(
				_(
					"Program {0}: temperature {1} °C is above the safe maximum {2} °C of equipment {3}."
				).format(program.name or program.program_code, _num(temp), _num(high), program.equipment)
			)
	pressure = flt(program.get("pressure"))
	max_pressure = flt(equipment.get("safe_pressure_max"))
	if pressure > 0 and max_pressure > 0 and pressure > max_pressure:
		warnings.append(
			_("Program {0}: pressure {1} bar is above the safe maximum {2} bar of equipment {3}.").format(
				program.name or program.program_code, _num(pressure), _num(max_pressure), program.equipment
			)
		)
	return warnings
