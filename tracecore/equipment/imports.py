"""Loại import Thiết bị và Chương trình xử lý cho khung `core.importer` (FEAT-011 Task 6, FR-M9-11; A-41).

Ghi qua controller `Equipment` / `Process Program` như nhập tay (định mức, tham số, chặn máy đã ngừng). Thiết bị không có
cột mã TB- (BRU-ID-006); "đã có" theo số serial. Chương trình nhiều dòng cùng mã: dòng đầu mang phần đầu, mỗi dòng
một tham số đánh giá chu trình (A-41 D5); máy tra theo số serial trong file.
"""

import frappe
from frappe import _

from tracecore.core.importer import Column, ImportKind, Issue

EQUIPMENT_TYPES = (
	"Steam Sterilizer",
	"Washer-Disinfector",
	"Plasma Sterilizer",
	"Sealer",
	"Laundry Washer",
	"Dryer",
	"Ultrasonic Cleaner",
)
PROGRAM_HEAD = (
	"program_name",
	"equipment_serial",
	"temperature",
	"pressure",
	"duration_min",
	"requires_bi",
	"kwh_per_cycle",
	"water_l_per_cycle",
)


# --- Thiết bị -------------------------------------------------------------------------------------------------


def _equipment_exists(serial_no):
	return bool(frappe.db.exists("Equipment", {"serial_no": serial_no}))


def _zone_issue(row, field, value):
	if value and not frappe.db.exists("Zone Station", value):
		return [Issue(row.row, "ZONE_NOT_FOUND", field, _("Zone {0} does not exist.").format(value))]
	return []


def _validate_equipment(unit):
	row = unit[0]
	return _zone_issue(row, "zone_in", row.values.get("zone_in")) + _zone_issue(
		row, "zone_out", row.values.get("zone_out")
	)


EQUIPMENT_FIELDS = (
	"equipment_name",
	"equipment_type",
	"manufacturer",
	"model",
	"serial_no",
	"capacity",
	"zone_in",
	"zone_out",
	"is_connected",
	"has_printout",
	"commissioned_on",
	"inspection_due",
	"purchase_value",
	"depreciation_years",
	"planned_loads_year",
	"safe_temp_min",
	"safe_temp_max",
	"safe_pressure_max",
)


def _write_equipment(unit):
	values = unit[0].values
	doc = frappe.get_doc(
		{
			"doctype": "Equipment",
			**{field: values.get(field) for field in EQUIPMENT_FIELDS if values.get(field) is not None},
		}
	)
	return doc.insert().name


# --- Chương trình xử lý ---------------------------------------------------------------------------------------


def _program_code(values):
	code = values.get("program_code")
	return code.strip().upper() if isinstance(code, str) else ""


def _program_exists(code):
	return bool(frappe.db.exists("Process Program", code))


def _machine(serial_no):
	return frappe.db.get_value("Equipment", {"serial_no": serial_no}, "name") if serial_no else None


def _validate_program(unit):
	head = unit[0]
	serial_no = head.values.get("equipment_serial")
	if not _machine(serial_no):
		return [
			Issue(
				head.row,
				"EQUIPMENT_NOT_FOUND",
				"equipment_serial",
				_("No equipment has serial number {0}.").format(serial_no),
			)
		]
	return []


def _write_program(unit):
	values = unit[0].values
	parameters = [
		{
			"parameter_name": row.values["parameter_name"],
			"unit": row.values.get("unit"),
			"min_value": row.values.get("min_value"),
			"max_value": row.values.get("max_value"),
			"required": 1 if row.values.get("required") else 0,
		}
		for row in unit
		if row.values.get("parameter_name")
	]
	doc = frappe.get_doc(
		{
			"doctype": "Process Program",
			"program_code": _program_code(values),
			"program_name": values["program_name"],
			"equipment": _machine(values["equipment_serial"]),
			"temperature": values.get("temperature"),
			"pressure": values.get("pressure"),
			"duration_min": values.get("duration_min"),
			"requires_bi": 1 if values.get("requires_bi") else 0,
			"kwh_per_cycle": values.get("kwh_per_cycle"),
			"water_l_per_cycle": values.get("water_l_per_cycle"),
			"parameters": parameters,
		}
	)
	return doc.insert().name


def import_kinds():
	"""Hook ``tracecore_import_kinds``."""
	return [
		ImportKind(
			key="equipment",
			label="Equipment",
			doctype="Equipment",
			columns=[
				Column("equipment_name", "Equipment Name", required=True),
				Column(
					"equipment_type", "Equipment Type", required=True, kind="select", options=EQUIPMENT_TYPES
				),
				Column("manufacturer", "Manufacturer", required=True),
				Column("model", "Model", required=True),
				Column("serial_no", "Serial No", required=True),
				Column("capacity", "Capacity"),
				Column("zone_in", "Zone In", required=True, help="Zone code, for example ZONE-01."),
				Column("zone_out", "Zone Out"),
				Column("is_connected", "Connected", kind="check"),
				Column("has_printout", "Has Printout", kind="check"),
				Column("commissioned_on", "Commissioned On", kind="date"),
				Column("inspection_due", "Inspection Due", kind="date"),
				Column("purchase_value", "Purchase Value", required=True, kind="float"),
				Column("depreciation_years", "Depreciation Years", required=True, kind="int"),
				Column("planned_loads_year", "Planned Loads per Year", required=True, kind="int"),
				Column("safe_temp_min", "Safe Temperature Min", kind="int"),
				Column("safe_temp_max", "Safe Temperature Max", kind="int"),
				Column("safe_pressure_max", "Safe Pressure Max", kind="float"),
			],
			code_field="serial_no",
			exists=_equipment_exists,
			validate=_validate_equipment,
			write=_write_equipment,
			forbidden_columns=("Equipment Code", "Equipment"),
			guide=("The equipment code (TB-) is issued by the system.",),
		),
		ImportKind(
			key="program",
			label="Process programs",
			doctype="Process Program",
			columns=[
				Column("program_code", "Program Code", required=True),
				Column("program_name", "Program Name", required=True),
				Column("equipment_serial", "Equipment Serial No", required=True),
				Column("temperature", "Temperature", kind="int"),
				Column("pressure", "Pressure", kind="float"),
				Column("duration_min", "Duration (min)", kind="int"),
				Column("requires_bi", "Requires BI", kind="check"),
				Column("kwh_per_cycle", "kWh per Cycle", kind="float"),
				Column("water_l_per_cycle", "Water (L) per Cycle", kind="float"),
				Column("parameter_name", "Parameter"),
				Column("unit", "Unit"),
				Column("min_value", "Min", kind="float"),
				Column("max_value", "Max", kind="float"),
				Column("required", "Required Parameter", kind="check"),
			],
			code_field="program_code",
			code_of=_program_code,
			exists=_program_exists,
			validate=_validate_program,
			write=_write_program,
			group_by="program_code",
			group_fields=PROGRAM_HEAD,
			guide=(
				"One row per cycle parameter. Repeat the program code on every row; program columns are read from the first row.",
			),
		),
	]
