"""A-102: `Sterilization Load.released_by` chỉ có khi mẻ đã giải phóng.

Dữ liệu cũ ghi người thao tác vào `released_by` khi chưa giải phóng (`released_at` trống). Chuyển sang `unloaded_by` nếu
trường này trống (đúng nghĩa dự phòng của A-86), rồi xóa. Không đụng mẻ đã có `released_at`. Chạy lại không đổi gì thêm.
"""

import frappe


def execute():
	rows = frappe.get_all(
		"Sterilization Load",
		filters={"released_by": ["is", "set"], "released_at": ["is", "not set"]},
		fields=["name", "released_by", "unloaded_by"],
	)
	for row in rows:
		frappe.db.set_value(
			"Sterilization Load",
			row.name,
			{"released_by": None, "unloaded_by": row.unloaded_by or row.released_by},
			update_modified=False,
		)
