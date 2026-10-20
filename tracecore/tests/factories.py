"""Factory dữ liệu test (F-5)."""

import frappe

from tracecore.core import gs1, step_gate


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


def _ref_name(ref):
	"""Tên bản ghi từ Document hoặc chuỗi tên."""
	return getattr(ref, "name", ref)


def next_free_test_gtin():
	"""GTIN-14 TEST (`gs1.make_test_gtin14`) nhỏ nhất chưa loại bộ nào dùng (D6).

	Xác định, không va chạm giữa các lần chạy test trên cùng site: tra các GTIN test đã có trong DB.
	"""
	used = set(
		frappe.get_all(
			"Instrument Set Type", filters={"gtin": ["like", f"{gs1.TEST_GTIN_PREFIX}%"]}, pluck="gtin"
		)
	)
	for serial in range(1, 100000):
		gtin = gs1.make_test_gtin14(serial)
		if gtin not in used:
			return gtin
	frappe.throw("No free test GTIN-14 left")


def make_set_type(
	type_code="TST",
	method="Steam",
	set_type_name=None,
	gtin="auto",
	default_pack_type=None,
	shelf_life_days=0,
	tray_image=None,
):
	"""Tạo (hoặc lấy) loại bộ.

	gtin: "auto" → GTIN test chưa dùng (mặc định); None → không có GTIN; chuỗi → dùng nguyên văn.
	Loại bộ đã có thì trả nguyên trạng.
	"""
	if frappe.db.exists("Instrument Set Type", type_code):
		return frappe.get_doc("Instrument Set Type", type_code)
	return frappe.get_doc(
		{
			"doctype": "Instrument Set Type",
			"type_code": type_code,
			"set_type_name": set_type_name or f"Test set {type_code}",
			"method": method,
			"gtin": next_free_test_gtin() if gtin == "auto" else gtin,
			"default_pack_type": default_pack_type,
			"shelf_life_days": shelf_life_days,
			"tray_image": tray_image,
		}
	).insert()


def make_instrument(code, name=None, interval=None, maint_type=None, image=None):
	"""Tạo (hoặc lấy) Instrument. interval: ngưỡng bảo dưỡng theo chu trình (None/0 = không nhắc)."""
	if frappe.db.exists("Instrument", code):
		return frappe.get_doc("Instrument", code)
	return frappe.get_doc(
		{
			"doctype": "Instrument",
			"instrument_code": code,
			"instrument_name": name or f"Test instrument {code}",
			"maint_interval_cycles": interval or 0,
			"maint_type": maint_type,
			"image": image,
		}
	).insert()


def make_bom(set_type, lines, version=1):
	"""Tạo các dòng Set BOM Item cho một phiên bản BOM; trả list Document theo thứ tự `lines`.

	lines: [(mã dụng cụ, số lượng), …]; position = thứ tự trong list (từ 1). Dụng cụ chưa có được tạo.
	"""
	set_type = _ref_name(set_type)
	rows = []
	for position, (instrument, qty) in enumerate(lines, 1):
		make_instrument(instrument)
		rows.append(
			frappe.get_doc(
				{
					"doctype": "Set BOM Item",
					"set_type": set_type,
					"bom_version": version,
					"instrument": instrument,
					"qty": qty,
					"position": position,
				}
			).insert()
		)
	return rows


def make_maintenance(set_unit, instrument, cycles_since=0, deferred_count=0):
	"""Tạo Instrument Maintenance cho cặp (set_unit, instrument); trùng cặp thì DuplicateEntryError."""
	instrument = _ref_name(make_instrument(_ref_name(instrument)))
	return frappe.get_doc(
		{
			"doctype": "Instrument Maintenance",
			"set_unit": _ref_name(set_unit),
			"instrument": instrument,
			"cycles_since_maint": cycles_since,
			"deferred_count": deferred_count,
		}
	).insert()


def make_assembly_record(set_unit, result="Pass", submit=True, notes=None):
	"""Tạo Assembly Record (stub T3) cho chu trình hiện hành của bộ; ghi sổ mặc định → ghi cổng T3."""
	doc = frappe.get_doc(
		{"doctype": "Assembly Record", "set_unit": _ref_name(set_unit), "result": result, "notes": notes}
	).insert()
	if submit:
		doc.submit()
	return doc


def make_cycle(set_unit, passed=("T1", "T2", "T3")):
	"""Mở chu trình mới cho bộ rồi ghi các bước `passed` Pass; trả cycle_no.

	T3 đi qua Assembly Record ghi sổ (đúng đường chứng từ); bước khác ghi thẳng bằng step_gate.record.
	"""
	set_unit = _ref_name(set_unit)
	cycle_no = step_gate.start_cycle(set_unit)
	for step in passed:
		if step == "T3":
			make_assembly_record(set_unit)
		else:
			step_gate.record(set_unit, step, "Pass")
	return cycle_no


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
