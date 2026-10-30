"""Loại chứng chỉ thành chữ tự điền (A-59): đổi 5 giá trị tiếng Anh của danh sách cũ sang chữ tiếng Việt đang hiển thị."""

import frappe
from frappe import _

OLD_TYPES = (
	"Practice License",
	"Infection Control",
	"Sterilization",
	"Pressure Equipment Operation",
	"Other",
)


def execute():
	for doctype in ("Certificate", "Competency Required Cert"):
		for old in OLD_TYPES:
			frappe.db.set_value(
				doctype,
				{"certificate_type": old},
				"certificate_type",
				_(old, lang="vi", context="Certificate"),
				update_modified=False,
			)
