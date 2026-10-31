"""A-64 (FEAT-051): trạm chuyển từ ``station_step`` sang chức năng và số trạm; chạy lại không đổi gì thêm.

Cột ``station_step`` cũ giữ nguyên trong DB, giá trị chép sang ``legacy_step``. Trạm mang mã ngoài bảng ánh xạ (T9, T10 từ
Property Setter tạm) không được gán chức năng và ghi log: sơ đồ riêng của từng site áp bằng ``setup.migrate_a64``.
"""

import re

import frappe

from tracecore.setup.seed import ensure_station_catalog

FUNCTIONS_BY_STEP = {
	"T1": ("RECEIVE",),
	"T2": ("WASH_LOAD", "WASH_UNLOAD"),
	"T3": ("ASSEMBLE",),
	"T4": ("PACK",),
	"T5": ("STERI_LOAD", "STERI_UNLOAD"),
	"T5b": ("STERI_UNLOAD",),
	"T6": ("PUTAWAY",),
	"T7": ("ISSUE",),
	"T8": ("USE",),
	"LIN": ("LINEN",),
	"WST": ("WASTE",),
}
HELP_KEY_BY_STEP = {step: functions[0] for step, functions in FUNCTIONS_BY_STEP.items()}
HELP_KEY_BY_STEP["T5b"] = "STERI_UNLOAD"
TEMP_PROPERTY_SETTER = "Zone Station-station_step-options"


def execute():
	ensure_station_catalog()
	_copy_legacy_step()
	for row in frappe.get_all(
		"Zone Station", filters={"is_zone": 0}, fields=["name", "legacy_step", "station_no", "is_active"]
	):
		_map_station(row)
	if frappe.db.exists("Property Setter", TEMP_PROPERTY_SETTER):
		frappe.delete_doc("Property Setter", TEMP_PROPERTY_SETTER, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype="Zone Station")
	_map_help_articles()


def _copy_legacy_step():
	if frappe.db.has_column("Zone Station", "station_step"):
		frappe.db.sql(
			"""update `tabZone Station` set legacy_step = station_step
			where station_step is not null and station_step != ''
			and (legacy_step is null or legacy_step = '')"""
		)


def _map_station(row):
	functions = FUNCTIONS_BY_STEP.get(row.legacy_step)
	if row.legacy_step and not functions:
		frappe.log_error(
			f"Station {row.name}: step {row.legacy_step} has no default function.", "A-64 migration"
		)
	has_rows = frappe.db.exists("Zone Station Function", {"parent": row.name, "parenttype": "Zone Station"})
	if functions and not has_rows:
		for idx, function in enumerate(functions, start=1):
			# không validate: site đang chạy có thể đang lệch quy tắc, R10 sửa sau trên form
			frappe.get_doc(
				{
					"doctype": "Zone Station Function",
					"parent": row.name,
					"parenttype": "Zone Station",
					"parentfield": "functions",
					"idx": idx,
					"station_function": function,
				}
			).db_insert()
	match = re.fullmatch(r"T(\d+)b?", row.legacy_step or "")
	number = int(match.group(1)) if match else 0
	if number and not row.station_no and not _number_taken(number, row.name):
		frappe.db.set_value("Zone Station", row.name, "station_no", number, update_modified=False)


def _number_taken(number, station):
	return frappe.db.exists(
		"Zone Station", {"is_zone": 0, "is_active": 1, "station_no": number, "name": ["!=", station]}
	)


def _map_help_articles():
	if not frappe.db.has_column("Help Article", "tc_station_key"):
		return
	for step, key in HELP_KEY_BY_STEP.items():
		frappe.db.set_value(
			"Help Article", {"tc_station_key": step}, "tc_station_key", key, update_modified=False
		)
