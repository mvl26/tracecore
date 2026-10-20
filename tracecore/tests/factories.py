"""Factory dữ liệu test (F-5)."""

import frappe


def make_user(email, roles=()):
	"""Tạo (hoặc lấy) System User với các role cho trước; trả email."""
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
	if roles:
		user.add_roles(*roles)
	return user.name


def make_set_unit(set_type=None, max_cycles=300, **kwargs):
	set_type = set_type or make_set_type().name
	return frappe.get_doc(
		{"doctype": "Set Unit", "set_type": set_type, "max_cycles": max_cycles, **kwargs}
	).insert()


def make_set_type(type_code="TST", method="Steam", set_type_name=None):
	if frappe.db.exists("Instrument Set Type", type_code):
		return frappe.get_doc("Instrument Set Type", type_code)
	return frappe.get_doc(
		{
			"doctype": "Instrument Set Type",
			"type_code": type_code,
			"set_type_name": set_type_name or f"Test set {type_code}",
			"method": method,
		}
	).insert()


ITEM_GROUP_ROOT = "All Item Groups"
ITEM_UOM = "Nos"


def ensure_item_masters():
	"""Item Group gốc và UOM "Nos" cho Item test.

	Site CI mới chưa chạy Setup Wizard của ERPNext nên chưa có hai bản ghi này.
	"""
	if not frappe.db.exists("UOM", ITEM_UOM):
		frappe.get_doc(
			{"doctype": "UOM", "uom_name": ITEM_UOM, "must_be_whole_number": 1, "enabled": 1}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("Item Group", ITEM_GROUP_ROOT):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": ITEM_GROUP_ROOT,
				"is_group": 1,
				"parent_item_group": "",
			}
		).insert(ignore_permissions=True)


def make_item(item_code, group, method=None, ci_class=None, shelf_life_days=None, has_batch_no=0):
	"""Tạo (hoặc lấy) Item ERPNext với các Custom Field CSSD (Item-tc_*).

	group: Packaging | Chemical Indicator | Label | Lubricant. Item đã có thì trả nguyên trạng.
	"""
	if frappe.db.exists("Item", item_code):
		return frappe.get_doc("Item", item_code)
	ensure_item_masters()
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": ITEM_GROUP_ROOT,
			"stock_uom": ITEM_UOM,
			"is_stock_item": 1,
			"has_batch_no": has_batch_no,
			"tc_item_group_cssd": group,
			"tc_compatible_method": method,
			"tc_ci_class": ci_class,
			"tc_shelf_life_days": shelf_life_days,
		}
	).insert(ignore_permissions=True)


def make_batch(item_code, batch_id, expiry_date=None):
	"""Tạo (hoặc lấy) Batch ERPNext; bật has_batch_no của Item nếu chưa."""
	if frappe.db.exists("Batch", batch_id):
		batch = frappe.get_doc("Batch", batch_id)
		if batch.item != item_code:
			frappe.throw(f"Batch {batch_id} belongs to Item {batch.item}, not {item_code}")
		return batch
	item = frappe.get_doc("Item", item_code)
	if not item.has_batch_no:
		item.has_batch_no = 1
		item.save(ignore_permissions=True)
	return frappe.get_doc(
		{"doctype": "Batch", "batch_id": batch_id, "item": item_code, "expiry_date": expiry_date}
	).insert(ignore_permissions=True)
