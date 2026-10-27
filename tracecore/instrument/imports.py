"""Loại import Dụng cụ, Loại bộ & BOM, Set Unit cho khung `core.importer` (FEAT-011 Task 4-5, FR-M9-11; A-41).

Ghi qua đúng đường của màn Desk: dụng cụ qua controller `Instrument` (luật mã, phương pháp, ảnh), loại bộ + BOM phiên
bản 1 qua `bom_versions.create_set_type` (A-07, S15), Set Unit qua `set_units.issue_batch` (A-13, G4: Set ID tự sinh,
BRU-ID-006). Loại bộ & BOM: nhiều dòng cùng mã loại bộ, dòng đầu mang phần đầu (A-41 D5).
"""

import frappe
from frappe import _

from tracecore.core.errors import BlockedError
from tracecore.core.importer import Column, ImportKind, Issue, RowError, department_ref
from tracecore.instrument import bom_versions, catalog, set_units

SPAULDING = ("Critical", "Semi-critical", "Non-critical")
INSTRUMENT_METHODS = ("Steam 121", "Steam 134", "Plasma", "EO")
SET_METHODS = ("Steam", "Plasma")
MAINT_TYPES = ("Lubrication", "Blade Check", "Screw Tightening", "Battery Replacement")
SET_ID_COLUMNS = ("Set ID", "Set Unit", "GIAI")
# cùng vai trò được cấp Set ID trên Desk (FEAT-016 G7, `v1.set_unit_lifecycle.ISSUE_ROLES`): Set Unit không tạo tay
SET_UNIT_ISSUE_ROLES = ("TC R02", "TC R10", "System Manager")


# --- Dụng cụ ---------------------------------------------------------------------------------------------------


def _instrument_code(values):
	return catalog.clean_code(values.get("instrument_code")) or values.get("instrument_code") or ""


def _instrument_exists(code):
	return bool(frappe.db.exists("Instrument", code))


def _validate_instrument(unit):
	row = unit[0]
	values = row.values
	issues = []
	if not catalog.clean_code(values.get("instrument_code")):
		issues.append(Issue(row.row, "CODE_INVALID", "instrument_code", catalog.code_rule_message()))
	group = values.get("instrument_group")
	if group and not frappe.db.exists("Instrument Group", group):
		issues.append(
			Issue(
				row.row,
				"GROUP_NOT_FOUND",
				"instrument_group",
				_("Instrument group {0} does not exist.").format(group),
			)
		)
	return issues


def _write_instrument(unit):
	values = unit[0].values
	doc = frappe.get_doc(
		{
			"doctype": "Instrument",
			"instrument_code": catalog.clean_code(values["instrument_code"]),
			"instrument_name": values["instrument_name"],
			"spaulding_class": values["spaulding_class"],
			"compatible_methods": [{"method": method} for method in values["compatible_methods"]],
			"instrument_group": values.get("instrument_group"),
			"manufacturer": values.get("manufacturer"),
			"model": values.get("model"),
			"maint_interval_cycles": values.get("maint_interval_cycles"),
			"maint_type": values.get("maint_type"),
			"max_cycles": values.get("max_cycles"),
			"value": values.get("value"),
		}
	)
	return doc.insert().name


# --- Loại bộ & BOM ---------------------------------------------------------------------------------------------

SET_TYPE_HEAD = (
	"set_type_name",
	"method",
	"department",
	"default_pack_type",
	"shelf_life_days",
	"gtin",
	"is_implant",
	"assembly_minutes",
)


def _type_code(values):
	code = values.get("type_code")
	return code.strip().upper() if isinstance(code, str) else ""


def _set_type_exists(code):
	return bool(frappe.db.exists("Instrument Set Type", code))


def _bom_lines(unit):
	return [
		{
			"instrument": row.values.get("instrument"),
			"qty": row.values.get("qty"),
			"position": row.values.get("position"),
		}
		for row in unit
	]


def _line_issues(unit, items):
	"""Lỗi dòng BOM của `bom_versions` (``row`` = thứ tự dòng gửi lên, 1..n) → lỗi đúng dòng Excel."""
	issues = []
	for item in items or []:
		index = int(item.get("row") or 1) - 1
		excel_row = unit[min(max(index, 0), len(unit) - 1)].row
		issues.append(
			Issue(excel_row, item.get("code") or "BOM_LINE_INVALID", "instrument", item.get("message") or "")
		)
	return issues


def _validate_set_type(unit):
	head = unit[0]
	values = head.values
	issues = []
	if not department_ref(values.get("department")):
		issues.append(
			Issue(
				head.row,
				"DEPARTMENT_NOT_FOUND",
				"department",
				_("Department {0} does not exist.").format(values.get("department")),
			)
		)
	if not frappe.db.exists("Item", values.get("default_pack_type") or ""):
		issues.append(
			Issue(
				head.row,
				"PACK_TYPE_NOT_FOUND",
				"default_pack_type",
				_("Pack type {0} does not exist.").format(values.get("default_pack_type")),
			)
		)
	rows = bom_versions.normalize_lines(_bom_lines(unit))
	return issues + _line_issues(unit, bom_versions.line_errors(values.get("method"), rows))


def _write_set_type(unit):
	values = unit[0].values
	header = {field: values.get(field) for field in SET_TYPE_HEAD if values.get(field) not in (None, "")}
	header["type_code"] = _type_code(values)
	header["department"] = department_ref(values.get("department"))
	try:
		return bom_versions.create_set_type(header, _bom_lines(unit))
	except BlockedError as error:
		if error.block.code == "BOM_LINE_INVALID":
			raise RowError(_line_issues(unit, error.block.items)) from None
		raise


# --- Set Unit --------------------------------------------------------------------------------------------------


def _set_type_ref(values):
	code = _type_code(values)
	return code if code and frappe.db.exists("Instrument Set Type", code) else None


def _set_unit_args(values):
	return {
		"department": department_ref(values.get("department")) if values.get("department") else None,
		"max_cycles": values.get("max_cycles"),
		"origin": values.get("origin") or "New",
		"cycles_used": values.get("cycles_used") or 0,
		"estimate_reason": values.get("estimate_reason"),
	}


def _validate_set_unit(unit):
	row = unit[0]
	values = row.values
	set_type = _set_type_ref(values)
	if not set_type:
		return [
			Issue(
				row.row,
				"SET_TYPE_NOT_FOUND",
				"type_code",
				_("Set type {0} does not exist.").format(values.get("type_code")),
			)
		]
	if set_units.parse_count(values.get("count")) is None:
		return [Issue(row.row, "COUNT_OUT_OF_RANGE", "count", set_units.count_block().reason)]
	try:
		set_units.precheck(set_type, **_set_unit_args(values))
	except BlockedError as error:
		return [Issue(row.row, error.block.code, None, error.block.reason)]
	except frappe.ValidationError as error:
		return [Issue(row.row, "VALUE_INVALID", None, frappe.utils.strip_html(str(error)))]
	return []


def _write_set_unit(unit):
	values = unit[0].values
	names = set_units.issue_batch(_set_type_ref(values), values["count"], **_set_unit_args(values))
	return names[0]


def import_kinds():
	"""Hook ``tracecore_import_kinds``."""
	return [
		ImportKind(
			key="instrument",
			label="Instruments",
			doctype="Instrument",
			columns=[
				Column("instrument_code", "Instrument Code", required=True, help=catalog.code_rule_message()),
				Column("instrument_name", "Instrument Name", required=True),
				Column("spaulding_class", "Spaulding Class", required=True, kind="select", options=SPAULDING),
				Column(
					"compatible_methods",
					"Compatible Methods",
					required=True,
					kind="list",
					options=INSTRUMENT_METHODS,
				),
				Column("instrument_group", "Instrument Group"),
				Column("manufacturer", "Manufacturer"),
				Column("model", "Model"),
				Column("maint_interval_cycles", "Maintenance Interval (cycles)", kind="int"),
				Column("maint_type", "Maintenance Type", kind="select", options=MAINT_TYPES),
				Column("max_cycles", "Max Cycles", kind="int"),
				Column("value", "Value (VND)", kind="float"),
			],
			code_field="instrument_code",
			code_of=_instrument_code,
			exists=_instrument_exists,
			validate=_validate_instrument,
			write=_write_instrument,
			guide=("Instrument photos are added afterwards with the photo zip import.",),
		),
		ImportKind(
			key="set_type",
			label="Set types and BOM",
			doctype="Instrument Set Type",
			columns=[
				Column("type_code", "Type Code", required=True, help="2-8 capital letters or digits."),
				Column("set_type_name", "Set Type Name", required=True),
				Column("method", "Method", required=True, kind="select", options=SET_METHODS),
				Column("department", "Department", required=True),
				Column(
					"default_pack_type",
					"Default Pack Type",
					required=True,
					help="Item code of the pack type.",
				),
				Column("shelf_life_days", "Shelf Life (days)", kind="int"),
				Column("gtin", "GTIN"),
				Column("is_implant", "Implant Set", kind="check"),
				Column("assembly_minutes", "Assembly Minutes", kind="int"),
				Column("instrument", "Instrument", required=True, help="Instrument code of one BOM line."),
				Column("qty", "Quantity", required=True, kind="int"),
				Column("position", "Position", kind="int"),
			],
			code_field="type_code",
			code_of=_type_code,
			exists=_set_type_exists,
			validate=_validate_set_type,
			write=_write_set_type,
			group_by="type_code",
			group_fields=SET_TYPE_HEAD,
			guide=(
				"One row per BOM line. Repeat the type code on every line; the set type columns are read from the first row of each type code.",
			),
		),
		ImportKind(
			key="set_unit",
			label="Set units (issue Set IDs)",
			doctype="Set Unit",
			columns=[
				Column("type_code", "Type Code", required=True),
				Column("count", "Count", required=True, kind="int", help="1 to 100 sets per row."),
				Column("department", "Department"),
				Column("max_cycles", "Max Cycles", kind="int"),
				Column("origin", "Origin", kind="select", options=set_units.ORIGINS),
				Column("cycles_used", "Cycles Used", kind="int"),
				Column("estimate_reason", "Estimate Reason"),
			],
			code_field="type_code",
			exists=lambda _code: False,  # mỗi dòng là một lô cấp Set ID mới, không có "đã có"
			validate=_validate_set_unit,
			write=_write_set_unit,
			forbidden_columns=SET_ID_COLUMNS,
			can_import=lambda: bool(set(frappe.get_roles()) & set(SET_UNIT_ISSUE_ROLES)),
			guide=("Set IDs are generated by the system; do not add a Set ID column.",),
		),
	]
