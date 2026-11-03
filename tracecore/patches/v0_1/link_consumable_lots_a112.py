"""A-112 E5: lô gõ ở Test đầu ngày và Kết quả chỉ thị trùng tên Batch của kho thì điền `batch` (kết quả chỉ thị điền
thêm vật tư nếu còn trống); lô không trùng giữ nguyên làm ghi chú, không bắt sửa tay."""

import frappe


def _link(doctype, extra_item_field=None):
	rows = frappe.get_all(
		doctype,
		filters={"lot": ["is", "set"], "batch": ["is", "not set"]},
		fields=["name", "lot"] + ([extra_item_field] if extra_item_field else []),
	)
	for row in rows:
		item = frappe.db.get_value("Batch", row.lot.strip(), "item")
		if not item:
			continue
		values = {"batch": row.lot.strip()}
		if extra_item_field and not row.get(extra_item_field):
			values[extra_item_field] = item
		frappe.db.set_value(doctype, row.name, values, update_modified=False)


def execute():
	_link("Daily Test")
	_link("Load Indicator Result", "indicator_item")
