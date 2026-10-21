"""Factory dữ liệu test (F-5)."""

import re
import unicodedata

import frappe
from frappe.model.naming import getseries
from frappe.utils import add_days, getdate, now_datetime, today

from tracecore.core import code_registry, gs1, step_gate
from tracecore.tests.utils import fixture_r10


def make_user(email, roles=()):
	"""Tạo (hoặc lấy) System User với các role cho trước; trả email."""
	with fixture_r10():
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


def make_instrument_group(group_name, interval=None, maint_type=None, description=None):
	"""Tạo (hoặc lấy) Instrument Group; trả tên nhóm.

	interval: ngưỡng bảo dưỡng của nhóm theo chu trình (None/0 = không có); nhóm đã có thì trả nguyên trạng.
	"""
	group_name = group_name.strip()
	if not frappe.db.exists("Instrument Group", group_name):
		frappe.get_doc(
			{
				"doctype": "Instrument Group",
				"group_name": group_name,
				"maint_interval_cycles": interval or 0,
				"maint_type": maint_type,
				"description": description,
			}
		).insert()
	return group_name


def attach_instrument_file(instrument, field, content, file_name, is_private=1):
	"""Tải `content` lên làm File đính vào trường `field` (``image``/``ifu``) của dụng cụ; trả File.

	Đi qua kiểm tra ``media.check_upload`` như khi tải lên từ Desk; gán URL vào trường rồi lưu dụng cụ để dùng.
	"""
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": is_private,
			"attached_to_doctype": "Instrument",
			"attached_to_name": instrument,
			"attached_to_field": field,
		}
	).insert()


def make_instrument(
	code,
	name=None,
	interval=None,
	maint_type=None,
	image=None,
	spaulding="Critical",
	methods=("Steam 134",),
	max_cycles=None,
	group=None,
	**kwargs,
):
	"""Tạo (hoặc lấy) Instrument đủ trường bắt buộc (FEAT-014).

	interval: ngưỡng bảo dưỡng theo chu trình (None/0 = không nhắc); max_cycles None/0 = cơ số Chưa xác định;
	group: tên Instrument Group (tạo nếu chưa có); kwargs: trường khác (manufacturer, model, value, item…).
	image/ifu: URL ghi thẳng vào DB sau khi tạo, như dữ liệu có trước FEAT-014 (không qua kiểm file của
	``media``); ảnh/IFU thật thì dùng ``attach_instrument_file`` rồi gán URL và lưu.
	"""
	if frappe.db.exists("Instrument", code):
		return frappe.get_doc("Instrument", code)
	media = {"image": image, "ifu": kwargs.pop("ifu", None)}
	doc = frappe.get_doc(
		{
			"doctype": "Instrument",
			"instrument_code": code,
			"instrument_name": name or f"Test instrument {code}",
			"maint_interval_cycles": interval or 0,
			"maint_type": maint_type,
			"spaulding_class": spaulding,
			"compatible_methods": [{"method": method} for method in methods],
			"max_cycles": max_cycles or 0,
			"instrument_group": make_instrument_group(group) if group else None,
			**kwargs,
		}
	).insert()
	media = {field: url for field, url in media.items() if url}
	if media:
		frappe.db.set_value("Instrument", doc.name, media, update_modified=False)
		doc.reload()
	return doc


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
	"""Tạo Instrument Maintenance cho cặp (set_unit, instrument); trùng cặp thì DuplicateEntryError.

	Dựng sẵn bộ đếm như dữ liệu có từ trước: đặt cờ ``flags.tc_maintenance`` của M1 (sửa tay bị chặn).
	"""
	instrument = _ref_name(make_instrument(_ref_name(instrument)))
	doc = frappe.get_doc(
		{
			"doctype": "Instrument Maintenance",
			"set_unit": _ref_name(set_unit),
			"instrument": instrument,
			"cycles_since_maint": cycles_since,
			"deferred_count": deferred_count,
		}
	)
	doc.flags.tc_maintenance = True
	return doc.insert()


def make_assembly_record(set_unit, result="Pass", submit=True, notes=None):
	"""Tạo Assembly Record (stub T3) cho chu trình hiện hành của bộ; ghi sổ mặc định → ghi cổng T3."""
	doc = frappe.get_doc(
		{"doctype": "Assembly Record", "set_unit": _ref_name(set_unit), "result": result, "notes": notes}
	).insert()
	if submit:
		doc.submit()
	return doc


def make_equipment(
	name="Máy hấp test",
	equipment_type="Steam Sterilizer",
	serial="SN-001",
	zone_in="ZONE-CLEAN",
	zone_out="ZONE-STERILE",
	purchase_value=600000000,
	years=10,
	loads=3000,
	**kwargs,
):
	"""Tạo Equipment (mã TB-#### do hệ thống sinh). `kwargs` ghi đè bất kỳ trường nào."""
	values = {
		"doctype": "Equipment",
		"equipment_name": name,
		"equipment_type": equipment_type,
		"manufacturer": "Test Maker",
		"model": "TM-1",
		"serial_no": serial,
		"zone_in": zone_in,
		"zone_out": zone_out,
		"purchase_value": purchase_value,
		"depreciation_years": years,
		"planned_loads_year": loads,
		**kwargs,
	}
	return frappe.get_doc(values).insert()


def make_program(equipment, code="MH-01-134", minutes=4, kwh=3.5, water=0, consumables=None, **kwargs):
	"""Tạo Process Program cho máy `equipment`. `kwargs` ghi đè bất kỳ trường nào (parameters, ...)."""
	values = {
		"doctype": "Process Program",
		"program_code": code,
		"program_name": f"Chương trình {code}",
		"equipment": equipment,
		"duration_min": minutes,
		"kwh_per_cycle": kwh,
		"water_l_per_cycle": water,
		"consumables": consumables or [],
		**kwargs,
	}
	return frappe.get_doc(values).insert()


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


def make_item(
	item_code,
	group,
	method=None,
	ci_class=None,
	shelf_life_days=None,
	has_batch_no=0,
	apply_rules=False,
):
	"""Tạo (hoặc lấy) Item ERPNext với các Custom Field CSSD (Item-tc_*).

	group: một giá trị của inventory.items.CSSD_GROUPS. Item đã có thì trả nguyên trạng.

	Mặc định dựng Item "cũ" (trước FEAT-041, dữ liệu của test FEAT-005/014/018): luật Item vật tư
	(inventory.items: tự bật cờ lô/hạn/bình quân, nhãn phải có phương pháp) chưa áp lúc tạo; đặt
	apply_rules=True để tạo Item như người dùng nhập trên Desk (test FEAT-041).
	"""
	if frappe.db.exists("Item", item_code):
		return frappe.get_doc("Item", item_code)
	ensure_item_masters()
	item = frappe.get_doc(
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
	)
	if not apply_rules:
		item.flags.tc_legacy_data = (
			True  # lần lưu kế tiếp của người dùng mới áp luật (FEAT-041 Review Focus 5)
		)
	return item.insert(ignore_permissions=True)


STOCK_COMPANY = "TraceCore Test"
STOCK_ABBR = "TCT"


def ensure_stock_masters():
	"""Company thử (đặt làm Company mặc định nếu site chưa có), kho mặc định, Fiscal Year và Stock Entry Type "Material Receipt" (idempotent).

	Site test/dev chưa chạy Setup Wizard của ERPNext nên chưa có các bản ghi này. Perpetual inventory tắt.
	Trả {"company", "warehouse"}.
	"""
	ensure_item_masters()
	if not frappe.db.exists("Warehouse Type", "Transit"):  # Company tạo kho Goods In Transit kiểu Transit
		frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)
	if not frappe.db.exists("Company", STOCK_COMPANY):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": STOCK_COMPANY,
				"abbr": STOCK_ABBR,
				"default_currency": "VND",
				"country": "Vietnam",
				"enable_perpetual_inventory": 0,
			}
		).insert(ignore_permissions=True)
	if not frappe.db.get_single_value("Global Defaults", "default_company"):
		frappe.db.set_single_value("Global Defaults", "default_company", STOCK_COMPANY)
	year = getdate(today()).year
	if not frappe.get_all(
		"Fiscal Year",
		filters=[["year_start_date", "<=", today()], ["year_end_date", ">=", today()]],
		limit=1,
	):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": f"{year} TCT",
				"year_start_date": f"{year}-01-01",
				"year_end_date": f"{year}-12-31",
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("Stock Entry Type", "Material Receipt"):
		frappe.get_doc(
			{"doctype": "Stock Entry Type", "name": "Material Receipt", "purpose": "Material Receipt"}
		).insert(ignore_permissions=True)
	return {"company": STOCK_COMPANY, "warehouse": f"Stores - {STOCK_ABBR}"}


def make_warehouse(name, is_group=False):
	"""Tạo (hoặc lấy) Warehouse của Company thử; trả tên đầy đủ (<name> - TCT)."""
	masters = ensure_stock_masters()
	full_name = f"{name} - {STOCK_ABBR}"
	if not frappe.db.exists("Warehouse", full_name):
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": name,
				"company": masters["company"],
				"parent_warehouse": f"All Warehouses - {STOCK_ABBR}",
				"is_group": 1 if is_group else 0,
			}
		).insert(ignore_permissions=True)
	return full_name


def make_supplier(name="TraceCore NCC"):
	"""Tạo (hoặc lấy) Supplier thử; trả tên."""
	if frappe.db.exists("Supplier", name):
		return name
	if not frappe.db.exists("Supplier Group", "All Supplier Groups"):
		frappe.get_doc(
			{"doctype": "Supplier Group", "supplier_group_name": "All Supplier Groups", "is_group": 1}
		).insert(ignore_permissions=True)
	return (
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_group": "All Supplier Groups",
				"supplier_type": "Company",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def build_receipt(lines, supplier, document_no, warehouse=None):
	"""Stock Entry Material Receipt chưa lưu cho vật tư CSSD.

	lines: danh sách dict {item_code, batch_id, expiry_date, qty, rate}. Chỉ điền các trường dòng cần khi
	chèn từ code (trên Desk, client script điền uom, conversion_factor).
	"""
	masters = ensure_stock_masters()
	warehouse = warehouse or masters["warehouse"]
	items = []
	for entry in lines:
		stock_uom = frappe.db.get_value("Item", entry["item_code"], "stock_uom")
		items.append(
			{
				"item_code": entry["item_code"],
				"qty": entry.get("qty", 1),
				"basic_rate": entry.get("rate", 0),
				"uom": stock_uom,
				"stock_uom": stock_uom,
				"conversion_factor": 1,
				"t_warehouse": warehouse,
				"tc_batch_id": entry.get("batch_id"),
				"tc_expiry_date": entry.get("expiry_date"),
			}
		)
	return frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"purpose": "Material Receipt",
			"company": masters["company"],
			"posting_date": today(),
			"to_warehouse": warehouse,
			"tc_supplier": supplier,
			"tc_document_no": document_no,
			"items": items,
		}
	)


def make_receipt(lines, supplier, document_no, warehouse=None, submit=True):
	"""Lập (và mặc định ghi sổ) phiếu nhập kho vật tư: Stock Entry Material Receipt theo lô/hạn."""
	doc = build_receipt(lines, supplier, document_no, warehouse)
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


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
		item.flags.tc_legacy_data = True  # chỉ bật cờ lô, không kéo theo luật hạn dùng của FEAT-041
		item.save(ignore_permissions=True)
	return frappe.get_doc(
		{"doctype": "Batch", "batch_id": batch_id, "item": item_code, "expiry_date": expiry_date}
	).insert(ignore_permissions=True)


def make_receipt_workbook(rows, headers=None):
	"""File .xlsx (bytes) cho nhập kho hàng loạt: dòng 1 là tiêu đề, `rows` là danh sách dòng giá trị thô.

	`headers` mặc định là tiêu đề của file mẫu; ô để nguyên kiểu (ngày, số, chuỗi) như người dùng nhập trong Excel.
	"""
	from io import BytesIO

	from openpyxl import Workbook

	from tracecore.inventory import receipt_import

	workbook = Workbook()
	sheet = workbook.active
	sheet.title = "Receipt"
	sheet.append(list(headers if headers is not None else receipt_import.header_labels()))
	for values in rows:
		sheet.append(list(values))
	buffer = BytesIO()
	workbook.save(buffer)
	return buffer.getvalue()


def attach_private_file(content, file_name):
	"""Tải `content` lên làm File riêng tư của người dùng hiện tại; trả `file_url`."""
	return (
		frappe.get_doc({"doctype": "File", "file_name": file_name, "content": content, "is_private": 1})
		.insert(ignore_permissions=True)
		.file_url
	)


LABEL_ITEMS = (("VT-NHAN-HAP", "Steam"), ("VT-NHAN-PLASMA", "Plasma"))


def make_label_items():
	"""Item nhãn hấp (`VT-NHAN-HAP`, Steam) và nhãn plasma (`VT-NHAN-PLASMA`, Plasma).

	Trả `(tên Item nhãn hấp, tên Item nhãn plasma)`.
	"""
	return tuple(make_item(code, "Label", method=method).name for code, method in LABEL_ITEMS)


def make_printer(station, label_item, host="", name="Test printer", supports_unicode=0):
	"""Tạo Printer ZPL 300 dpi tại trạm với loại nhãn đang lắp `label_item`; trả tên Printer (PRN-###)."""
	return (
		frappe.get_doc(
			{
				"doctype": "Printer",
				"printer_name": name,
				"station": station,
				"host": host,
				"label_type_loaded": _ref_name(label_item),
				"supports_unicode": supports_unicode,
			}
		)
		.insert()
		.name
	)


def deactivate_printers(station):
	"""Tắt mọi máy in đang hoạt động của `station`: site test có thể còn máy in từ lần chạy/dữ liệu mẫu khác.

	Gọi trước khi tạo máy in của test để biết chính xác trạm có bao nhiêu máy in hoạt động.
	"""
	frappe.db.set_value("Printer", {"station": station}, "is_active", 0)


def make_roll(label_item):
	"""Cấp mã cuộn nhãn `CN-#####` cho Item nhãn và ghi Code Registry (D2: FEAT-005 cấp mã thật); trả mã cuộn."""
	label_item = _ref_name(label_item)
	while True:
		code = f"CN-{getseries('CN-', 5)}"
		if not code_registry.is_issued(code):
			code_registry.register(code, code_registry.ROLL_PREFIX, "Item", label_item)
			return code


def make_ci_batch(method="Steam", ci_class="5", expiry_days=30, batch_id=None):
	"""Lô chỉ thị hóa học (Batch ERPNext) của Item `CI<lớp>-<PHƯƠNG PHÁP>`; trả tên Batch.

	expiry_days: hạn dùng = hôm nay + expiry_days (âm = đã hết hạn). Không truyền batch_id thì mã lô
	suy ra từ (phương pháp, lớp, expiry_days) nên gọi lại cùng tham số trả lại đúng lô đó.
	"""
	item_code = f"CI{ci_class}-{method.upper()}"
	make_item(item_code, "Chemical Indicator", method=method, ci_class=ci_class)
	sign = "P" if expiry_days >= 0 else "M"
	batch_id = batch_id or f"LOT-{item_code}-{sign}{abs(expiry_days)}"
	return make_batch(item_code, batch_id, expiry_date=add_days(today(), expiry_days)).name


def _slug(text):
	"""ASCII IN HOA, gạch nối: "Giấy crepe" -> "GIAY-CREPE" (mã Item không dấu, an toàn)."""
	text = text.replace("đ", "d").replace("Đ", "D")
	ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
	return re.sub(r"[^A-Z0-9]+", "-", ascii_text.upper()).strip("-") or "GOI"


def make_pack_type(name="Giấy crepe", shelf_life_days=30):
	"""Item loại gói (nhóm Packaging) có hạn lưu `shelf_life_days`; trả mã Item `VT-GOI-<tên không dấu>`.

	Gọi lại với hạn lưu khác thì cập nhật hạn lưu của Item đó (không giữ giá trị cũ một cách âm thầm).
	"""
	item = make_item(f"VT-GOI-{_slug(name)}", "Packaging", shelf_life_days=shelf_life_days)
	if item.tc_shelf_life_days != shelf_life_days:
		item.tc_shelf_life_days = shelf_life_days
		item.save(ignore_permissions=True)
	return item.name


def next_free_test_cycle_id(day=None):
	"""Cycle ID thử `CY-YYMMDD-9NNN` chưa có Pack nào dùng, đếm lùi từ 9999.

	Dãy 9xxx tách khỏi dãy thật (0001 trở đi) mà `packing.generate` cấp trong cùng ngày.
	"""
	prefix = f"CY-{getdate(day or today()):%y%m%d}-"
	for serial in range(9999, 0, -1):
		cycle_id = f"{prefix}{serial:04d}"
		if not frappe.db.exists("Pack", cycle_id):
			return cycle_id
	frappe.throw("No free test Cycle ID left")


T4_STATION = "TR-004"
_SET_TYPE_KWARGS = ("type_code", "set_type_name", "gtin", "shelf_life_days", "tray_image")


def _free_type_code(prefix="T4"):
	"""Mã loại bộ chưa dùng `T4NNNN`: mỗi bộ sẵn sàng T4 có loại bộ (và BOM) riêng."""
	for serial in range(1, 10000):
		code = f"{prefix}{serial:04d}"
		if not frappe.db.exists("Instrument Set Type", code):
			return code
	frappe.throw("No free set type code left")


def make_t4_ready_set(method="Steam", bom=(("KC-01", 2), ("KC-02", 1)), with_printer=True, **set_kwargs):
	"""Bộ sẵn sàng đóng gói tại T4 (TR-004): đã qua T1..T3 Đạt trong chu trình 1.

	Loại bộ mới (mã `T4NNNN`, GTIN test, BOM phiên bản 1 = `bom`, loại gói mặc định `make_pack_type()`
	30 ngày), lô chỉ thị loại 5 đúng phương pháp, và (nếu `with_printer`) máy in tại TR-004 đang lắp nhãn
	đúng phương pháp. `set_kwargs`: khóa của loại bộ (`type_code, set_type_name, gtin, shelf_life_days,
	tray_image`) đi vào `make_set_type`, còn lại (`max_cycles, is_loaner, department`…) vào `make_set_unit`.
	Trả `frappe._dict(set_id, set_type, gtin, pack_type, ci_batch, printer, instruments)`.
	"""
	type_kwargs = {key: set_kwargs.pop(key) for key in _SET_TYPE_KWARGS if key in set_kwargs}
	pack_type = make_pack_type()
	set_type = make_set_type(
		type_kwargs.pop("type_code", None) or _free_type_code(),
		method=method,
		default_pack_type=pack_type,
		**type_kwargs,
	)
	make_bom(set_type, bom)
	set_unit = make_set_unit(set_type.name, **set_kwargs)
	make_cycle(set_unit)
	printer = None
	if with_printer:
		steam_label, plasma_label = make_label_items()
		printer = make_printer(T4_STATION, steam_label if method == "Steam" else plasma_label)
	return frappe._dict(
		set_id=set_unit.name,
		set_type=set_type.name,
		gtin=set_type.gtin,
		pack_type=pack_type,
		ci_batch=make_ci_batch(method),
		printer=printer,
		instruments=[code for code, _qty in bom],
	)


def make_pack(set_unit, cycle_id=None, submit=True, **fields):
	"""Tạo Pack cho bộ `set_unit` (như `packing.generate` sẽ làm): đặt tên bằng `insert(set_name=…)`.

	Mặc định: loại gói `make_pack_type()`, hạn 30 ngày từ hôm nay (nguồn Pack Type), người đóng gói là
	user đang đăng nhập, trạng thái Packed, đã ghi sổ. `fields` ghi đè bất kỳ trường nào của Pack.
	"""
	set_unit = frappe.get_doc("Set Unit", _ref_name(set_unit))
	set_type = frappe.get_doc("Instrument Set Type", set_unit.set_type)
	packed_at = fields.pop("packed_at", None) or now_datetime()
	values = {
		"doctype": "Pack",
		"set_unit": set_unit.name,
		"cycle_no": set_unit.current_cycle_no or 1,
		"method": set_type.method,
		"pack_type": make_pack_type(),
		"packed_by_user": frappe.session.user,
		"packed_at": packed_at,
		"expiry": add_days(getdate(packed_at), 30),
		"shelf_life_days_applied": 30,
		"shelf_life_source": "Pack Type",
		"gtin": set_type.gtin,
		**fields,
	}
	doc = frappe.get_doc(values).insert(set_name=cycle_id or next_free_test_cycle_id(packed_at))
	if submit:
		doc.submit()
	return doc
