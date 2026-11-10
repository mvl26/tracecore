"""A-146 Q1 (FEAT-068; FR-M14-07.1): cờ `Department.tc_clinical` (khoa lâm sàng) cho site đang chạy.

Patch chạy trước khi `migrate` đồng bộ fixtures, nên tạo Custom Field từ `fixtures/custom_field.json` nếu chưa có, rồi
điền sẵn từ cờ khoa nội trú `tc_inpatient` để tỷ lệ khoa có phòng cách ly đạt có mẫu số ngay sau khi nâng cấp; R10 sửa
lại khoa lâm sàng ngoại trú sau. Chỉ chạy một lần (patches.txt); khoa đã đánh dấu giữ nguyên.
"""

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

FIELD = "Department-tc_clinical"


def _fixture():
	path = Path(frappe.get_app_path("tracecore", "fixtures", "custom_field.json"))
	row = next(item for item in json.loads(path.read_text()) if item["name"] == FIELD)
	return {key: value for key, value in row.items() if key not in ("doctype", "dt", "name")}


def execute():
	if not frappe.db.exists("Custom Field", FIELD):
		create_custom_field("Department", _fixture())
	if not frappe.db.has_column("Department", "tc_inpatient"):
		return
	frappe.db.sql(
		"""update `tabDepartment` set tc_clinical = 1
		where ifnull(tc_inpatient, 0) = 1 and ifnull(tc_clinical, 0) = 0"""
	)
