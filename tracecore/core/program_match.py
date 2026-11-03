"""Chương trình theo máy của loại bộ (A-110, ticket #1865; FR-M1-03.7, FR-M1-03.8, FR-M2-03.7/.8, FR-M2-09.7/.8).

Bảng con ``Set Type Program`` của ``Instrument Set Type`` khai chương trình mặc định và chương trình cho phép của loại
bộ trên từng máy. M1 (kiểm khi lưu) và M2 (T2, T5) cùng gọi module này nên không import chéo nhau.

* Mỗi dòng trỏ tới một chương trình, tức một máy; công đoạn suy từ loại máy (D1, D2).
* Loại bộ chưa có dòng nào cho máy thì quy tắc không áp dụng: ``Unmapped`` (D4).
* Chương trình ngoài danh sách của loại bộ đã khai xử lý theo ``TraceCore Settings.program_control`` (D7):
  ``Warn`` nhận, ``Block`` từ chối ``PROGRAM_NOT_FOR_SET``, ``Override`` cần lý do khi Hoàn thành nạp.
  Tương thích phương pháp và loại gói (BRU-REP-004) không đi qua đây và luôn chặn.
"""

import frappe
from frappe import _

from tracecore.core.errors import Block, BlockedError

STAGES = {
	"Ultrasonic Cleaner": "Ultrasonic Washing",
	"Washer-Disinfector": "Washer-Disinfection",
	"Steam Sterilizer": "Sterilization",
	"Plasma Sterilizer": "Sterilization",
}
STERILIZER_METHODS = {"Steam Sterilizer": "Steam", "Plasma Sterilizer": "Plasma"}
TEST_PROGRAM = "Test"

DEFAULT, ALLOWED, OUTSIDE, UNMAPPED = "Default", "Allowed", "Outside", "Unmapped"
WARN, BLOCK, OVERRIDE = "Warn", "Block", "Override"


def stage_of(equipment_type):
	return STAGES.get(equipment_type)


# --- Danh mục (FR-M1-03.7, FR-M1-03.8) -----------------------------------------------------------------------


def validate_rows(doc) -> None:
	"""Điền máy, loại máy, công đoạn của từng dòng ``doc.programs`` rồi kiểm; sai thì từ chối cả lần lưu.

	Chương trình phải còn dùng, không phải chương trình test, thuộc máy rửa hoặc máy tiệt khuẩn, không trùng dòng;
	chương trình tiệt khuẩn khớp phương pháp của loại bộ; mỗi máy tối đa một dòng Mặc định (BRU-REP-017).
	"""
	errors, seen, defaults = [], set(), {}
	for row in doc.get("programs") or []:
		program = frappe.db.get_value(
			"Process Program",
			row.program,
			["name", "program_name", "equipment", "is_active", "program_kind"],
			as_dict=True,
		)
		if not program:
			errors.append(_("Row {0}: program {1} does not exist.").format(row.idx, row.program or "-"))
			continue
		equipment_type = frappe.db.get_value("Equipment", program.equipment, "equipment_type")
		row.equipment = program.equipment
		row.equipment_type = equipment_type
		row.stage = stage_of(equipment_type)
		label = f"{program.name} ({program.program_name})"
		if not row.stage:
			errors.append(
				_(
					"Row {0}: program {1} belongs to equipment {2}, which is not a washer or a sterilizer."
				).format(row.idx, label, program.equipment)
			)
			continue
		if not program.is_active:
			errors.append(_("Row {0}: program {1} is no longer in use.").format(row.idx, label))
		if program.program_kind == TEST_PROGRAM:
			errors.append(
				_("Row {0}: program {1} is a test program and takes no set.").format(row.idx, label)
			)
		method = STERILIZER_METHODS.get(equipment_type)
		if method and doc.method and method != doc.method:
			errors.append(
				_("Row {0}: program {1} runs {2} sterilization, but this set type uses {3}.").format(
					row.idx, label, _(method), _(doc.method)
				)
			)
		if program.name in seen:
			errors.append(_("Row {0}: program {1} is listed twice.").format(row.idx, label))
		seen.add(program.name)
		if row.is_default:
			if program.equipment in defaults:
				errors.append(
					_("Row {0}: equipment {1} already has default program {2}.").format(
						row.idx, program.equipment, defaults[program.equipment]
					)
				)
			else:
				defaults[program.equipment] = program.name
	if errors:
		frappe.throw("<br>".join(errors), title=_("Programs by machine are not valid"))


def set_types_of(program):
	"""Loại bộ dùng `program`: ``[{"set_type", "set_type_name", "method", "is_default", "mismatch"}]`` (FR-M5-02.5).

	``mismatch`` = 1 khi chương trình tiệt khuẩn khác phương pháp của loại bộ (dữ liệu cũ, hoặc loại bộ đổi sau đó).
	"""
	method = STERILIZER_METHODS.get(
		frappe.db.get_value(
			"Equipment", frappe.db.get_value("Process Program", program, "equipment"), "equipment_type"
		)
	)
	rows = frappe.db.sql(
		"""select row.parent as set_type, st.set_type_name, st.method, row.is_default
		from `tabSet Type Program` row
		join `tabInstrument Set Type` st on st.name = row.parent
		where row.parenttype = 'Instrument Set Type' and row.program = %s
		order by row.is_default desc, row.parent asc""",
		program,
		as_dict=True,
	)
	for row in rows:
		row["is_default"] = int(row.is_default or 0)
		row["mismatch"] = int(bool(method and row.method != method))
	return rows


# --- Trạm T2, T5 (FR-M2-03.7/.8, FR-M2-09.7/.8) --------------------------------------------------------------


def machine_map(equipment):
	"""``{loại bộ: {"default": chương trình | None, "allowed": [chương trình]}}`` của máy `equipment`.

	Chỉ chương trình còn dùng, không phải test; ``allowed`` gồm cả chương trình mặc định, theo thứ tự dòng khai.
	Trả kèm khi quét máy để màn trạm tự chọn và gắn nhãn dòng được cả khi offline; server kiểm lại khi nạp.
	"""
	rows = frappe.db.sql(
		"""select row.parent as set_type, row.program, row.is_default
		from `tabSet Type Program` row
		join `tabProcess Program` program on program.name = row.program
		where row.parenttype = 'Instrument Set Type' and program.equipment = %s
			and program.is_active = 1 and ifnull(program.program_kind, '') != %s
		order by row.parent asc, row.idx asc""",
		(equipment, TEST_PROGRAM),
		as_dict=True,
	)
	mapping = {}
	for row in rows:
		entry = mapping.setdefault(row.set_type, {"default": None, "allowed": []})
		entry["allowed"].append(row.program)
		if row.is_default:
			entry["default"] = row.program
	return mapping


def entry_fit(entry, program):
	if not entry:
		return UNMAPPED
	if program and program == entry["default"]:
		return DEFAULT
	return ALLOWED if program in entry["allowed"] else OUTSIDE


def fit(set_type, equipment, program):
	return entry_fit(machine_map(equipment).get(set_type), program)


def suggest(set_types, mapping):
	"""Chương trình nên chạy cho các loại bộ `set_types` trên máy của `mapping` (D5, D6).

	``common`` là chương trình được phép cho mọi loại bộ đã khai, xếp theo số loại bộ nhận nó làm mặc định;
	``conflict`` khi các loại bộ có mặc định khác nhau hoặc không có chương trình chung (gợi ý tách lô/mẻ).
	"""
	entries = {name: mapping[name] for name in dict.fromkeys(set_types or []) if name in mapping}
	if not entries:
		return {"program": None, "conflict": False, "common": [], "defaults": {}}
	defaults = {name: entry["default"] for name, entry in entries.items() if entry["default"]}
	votes = {}
	for program in defaults.values():
		votes[program] = votes.get(program, 0) + 1
	allowed = [set(entry["allowed"]) for entry in entries.values()]
	common = sorted(set.intersection(*allowed), key=lambda program: (-votes.get(program, 0), program))
	if common:
		program = common[0]
	else:
		program = max(votes, key=lambda name: (votes[name], name)) if votes else None
	return {
		"program": program,
		"conflict": len(set(defaults.values())) > 1 or not common,
		"common": common,
		"defaults": defaults,
	}


def control_level():
	return frappe.db.get_single_value("TraceCore Settings", "program_control") or WARN


def _set_label(set_type):
	return frappe.db.get_value("Instrument Set Type", set_type, "set_type_name") or set_type


def _program_label(program):
	return frappe.db.get_value("Process Program", program, "program_name") or program


def label(set_type, equipment, program):
	"""Nhãn của một bộ/gói trên máy, không chặn: ``{"fit", "default"}``; chưa có chương trình thì ``fit`` là None."""
	entry = machine_map(equipment).get(set_type)
	return {
		"fit": entry_fit(entry, program) if program else None,
		"default": entry["default"] if entry else None,
	}


def admit(set_type, equipment, program):
	"""Như `label`, nhưng mức ``Block`` từ chối bộ/gói ngoài danh sách (D7)."""
	result = label(set_type, equipment, program)
	if result["fit"] == OUTSIDE and control_level() == BLOCK:
		raise BlockedError(
			Block(
				"PROGRAM_NOT_FOR_SET",
				_("Program is not listed for this set"),
				_("Set type {0} is not listed for program {1} on equipment {2}.").format(
					_set_label(set_type), _program_label(program), equipment
				),
				_("Choose a program listed for this set type, or load the set separately."),
				object_type="Process Program",
				object_name=program,
			)
		)
	return result


def review(set_types, equipment, program, operator=None, override_reason=None):
	"""Trường truy vết của lô/mẻ khi Hoàn thành nạp (D8): ``suggested_program``, ``program_override_by``, ``_reason``.

	Có loại bộ ngoài danh sách: mức ``Override`` cần lý do (``PROGRAM_OVERRIDE_REASON_REQUIRED``); mức ``Block`` không
	tới được đây vì bộ đã bị loại lúc nạp, vẫn chặn cho chắc.
	"""
	mapping = machine_map(equipment)
	outside = sorted(
		name for name in set(set_types or []) if entry_fit(mapping.get(name), program) == OUTSIDE
	)
	reason = (override_reason or "").strip() or None
	level = control_level()
	if outside and level == BLOCK:
		raise BlockedError(
			Block(
				"PROGRAM_NOT_FOR_SET",
				_("Program is not listed for these sets"),
				_("Set types {0} are not listed for program {1} on equipment {2}.").format(
					", ".join(_set_label(name) for name in outside), _program_label(program), equipment
				),
				_("Choose a program listed for these set types, or load them separately."),
				object_type="Process Program",
				object_name=program,
			)
		)
	if outside and level == OVERRIDE and not reason:
		raise BlockedError(
			Block(
				"PROGRAM_OVERRIDE_REASON_REQUIRED",
				_("Reason needed to use this program"),
				_("Program {0} is not listed for set types {1}.").format(
					_program_label(program), ", ".join(_set_label(name) for name in outside)
				),
				_("Enter the reason for using this program, then complete loading again."),
				object_type="Process Program",
				object_name=program,
			)
		)
	return {
		"suggested_program": suggest(set_types, mapping)["program"],
		"program_override_by": operator if outside else None,
		"program_override_reason": reason if outside else None,
	}
