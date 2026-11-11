"""A-138 d (FEAT-094): dòng nhân sự KSNK có trước FEAT-094 chưa có vai trò → Giám sát viên (Surveillance Officer).

Chạy sau khi đồng bộ DocType (post_model_sync) để cột ``ic_role`` đã có; dòng đã có vai trò giữ nguyên.
"""

import frappe


def execute():
	frappe.db.sql(
		"""update `tabIC Surveillance Staff` set ic_role = %s where ifnull(ic_role, '') = ''""",
		"Surveillance Officer",
	)
