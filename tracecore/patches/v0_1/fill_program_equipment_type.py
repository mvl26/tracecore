"""Điền `Process Program.equipment_type` theo máy cho chương trình cũ (A-110).

Trường lấy từ máy (`fetch_from: equipment.equipment_type`) chỉ được điền khi chương trình được lưu lại, nên chương trình
tạo trước A-110 để trống. Ô chọn chương trình ở tab Chương trình theo máy của loại bộ lọc theo trường này nên không thấy
các chương trình đó. Patch cũng sửa giá trị lệch khi loại máy đã đổi sau đó. Không đổi `modified`.
"""

import frappe


def execute():
	frappe.db.sql(
		"""
		update `tabProcess Program` pp
		join `tabEquipment` eq on eq.name = pp.equipment
		set pp.equipment_type = eq.equipment_type
		where ifnull(eq.equipment_type, '') != '' and ifnull(pp.equipment_type, '') != eq.equipment_type
		"""
	)
