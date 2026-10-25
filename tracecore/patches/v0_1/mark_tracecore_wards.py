"""A-22: đánh dấu `Department.tc_is_ward` cho khoa đã có dữ liệu TraceCore (loại bộ, phiếu tiếp nhận, phiếu cấp phát,
cơ số khoa), để T1/T7 không mất khoa đang dùng khi chỉ liệt kê khoa dùng TraceCore.

Patch chạy trước khi `migrate` đồng bộ fixtures nên tự tạo Custom Field (cùng định nghĩa với `fixtures/custom_field.json`)
khi cột chưa có; fixtures sau đó chỉ cập nhật lại cùng nội dung.
"""

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

SOURCES = (
	("Instrument Set Type", "department"),
	("Dirty Receipt", "department"),
	("Issue Note", "department"),
	("Par Level", "department"),
)


def _field_definition():
	path = frappe.get_app_path("tracecore", "fixtures", "custom_field.json")
	with open(path, encoding="utf-8") as handle:
		row = next(item for item in json.load(handle) if item["name"] == "Department-tc_is_ward")
	return {key: value for key, value in row.items() if key not in ("doctype", "dt", "name")}


def execute():
	if not frappe.db.has_column("Department", "tc_is_ward"):
		create_custom_fields({"Department": [_field_definition()]}, update=True)
	for doctype, field in SOURCES:
		if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, field):
			continue
		for name in frappe.get_all(doctype, filters={field: ["is", "set"]}, pluck=field, distinct=True):
			if frappe.db.exists("Department", name):
				frappe.db.set_value("Department", name, "tc_is_ward", 1, update_modified=False)
