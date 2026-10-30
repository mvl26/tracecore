"""Factory dữ liệu test (F-5)."""

import re
import unicodedata

import frappe
from frappe.model.naming import getseries
from frappe.utils import add_days, get_first_day, get_last_day, getdate, now_datetime, today

from tracecore.core import code_registry, gs1, step_gate
from tracecore.instrument import bom_versions, set_units
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


def make_set_unit(set_type=None, max_cycles=300, department=None, **kwargs):
	"""Một Set Unit Mới tạo qua đường cấp Set ID (FEAT-016 G4: cờ cấp + ``step_gate.init_unit``); trả Document.

	Dùng đường ghi của ``set_units.issue_batch`` nhưng KHÔNG kiểm điều kiện cấp (``set_units._create_units``), để dựng
	bộ như dữ liệu có trước FEAT-016: loại bộ chưa có BOM/khoa, bộ không có khoa (`department` None). `kwargs`: trường
	khác (vd ``is_loaner``); trường vòng đời truyền vào bị đặt lại về mặc định như khi cấp. Không có Audit lô.
	"""
	set_type = set_type or make_set_type().name
	name = set_units._create_units(set_type, 1, department, max_cycles, fields=kwargs)[0]
	return frappe.get_doc("Set Unit", name)


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


TEST_DEPARTMENT = "Test CSSD department"
# Loại gói mặc định của loại bộ test khi không truyền: hạn lưu dài để mọi ghi đè hợp lệ (< hạn loại gói) đều nhận
AUTO_PACK_TYPE = ("Test auto", 365)


def make_department(department_name=TEST_DEPARTMENT):
	"""Tạo (hoặc lấy) Department (khoa, ERPNext); trả tên Department.

	Có Company (site đã chạy Setup Wizard) thì gắn Company mặc định; site CI mới chưa có Company nên tạo không kèm
	Company (bỏ kiểm bắt buộc, như dữ liệu test của các factory ERPNext khác).
	"""
	existing = frappe.db.get_value("Department", {"department_name": department_name}, "name")
	if existing:
		if not frappe.db.get_value("Department", existing, "tc_is_ward"):
			frappe.db.set_value("Department", existing, "tc_is_ward", 1)  # khoa dùng TraceCore (A-22)
		return existing
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	doc = frappe.get_doc(
		{"doctype": "Department", "department_name": department_name, "company": company, "tc_is_ward": 1}
	)
	doc.flags.ignore_mandatory = not company
	return doc.insert(ignore_permissions=True).name


def make_set_type(
	type_code="TST",
	method="Steam",
	set_type_name=None,
	gtin="auto",
	default_pack_type="auto",
	shelf_life_days=0,
	tray_image=None,
	department="auto",
	is_implant=0,
	assembly_minutes=0,
	bom=None,
):
	"""Tạo (hoặc lấy) loại bộ.

	gtin: "auto" → GTIN test chưa dùng (mặc định); None → không có GTIN; chuỗi → dùng nguyên văn.
	department: "auto" → ``make_department()``; default_pack_type: "auto" → loại gói test hạn 365 ngày
	(``AUTO_PACK_TYPE``); None → để trống (kiểm trường bắt buộc). bom: ``[(mã dụng cụ, số lượng), …]`` → tạo loại bộ
	cùng BOM v1 qua ``bom_versions.create_set_type`` (như R02 lưu lần đầu, FR-M1-03.1); không có bom → loại bộ chưa có
	BOM như dữ liệu có trước FEAT-015 (ghi với cờ dịch vụ ``flags.tc_bom``), thêm BOM sau bằng ``make_bom``.
	Loại bộ đã có thì trả nguyên trạng.
	"""
	if frappe.db.exists("Instrument Set Type", type_code):
		return frappe.get_doc("Instrument Set Type", type_code)
	values = {
		"type_code": type_code,
		"set_type_name": set_type_name or f"Test set {type_code}",
		"method": method,
		"gtin": next_free_test_gtin() if gtin == "auto" else gtin,
		"department": make_department() if department == "auto" else department,
		"default_pack_type": make_pack_type(*AUTO_PACK_TYPE)
		if default_pack_type == "auto"
		else default_pack_type,
		"shelf_life_days": shelf_life_days,
		"is_implant": is_implant,
		"assembly_minutes": assembly_minutes,
	}
	if bom:
		_ensure_bom_instruments(bom)
		name = bom_versions.create_set_type(values, [{"instrument": code, "qty": qty} for code, qty in bom])
		if tray_image:
			frappe.db.set_value("Instrument Set Type", name, "tray_image", tray_image, update_modified=False)
		return frappe.get_doc("Instrument Set Type", name)
	doc = frappe.get_doc({"doctype": "Instrument Set Type", **values})
	doc.flags.tc_bom = True
	doc.insert()
	doc.flags.tc_bom = False  # doc trả về lưu tiếp như người dùng (không mang cờ dịch vụ)
	if tray_image:
		# URL ghi thẳng như dữ liệu có trước FEAT-015 (không qua kiểm file của media); ảnh thật: attach_set_type_photo
		frappe.db.set_value("Instrument Set Type", doc.name, "tray_image", tray_image, update_modified=False)
		doc.reload()
		doc.flags.tc_bom = False
	return doc


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


def attach_set_type_photo(set_type, field, content, file_name, is_private=1):
	"""Tải `content` lên làm File đính vào ảnh bộ đã xếp `field` (``tray_image``/``tray_image_2``/``tray_image_3``)
	của loại bộ; trả File. Đi qua đúng kiểm tra file của ``media`` như ảnh dụng cụ (FEAT-015 S6); gán URL vào trường
	rồi lưu loại bộ để dùng.
	"""
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": is_private,
			"attached_to_doctype": "Instrument Set Type",
			"attached_to_name": _ref_name(set_type),
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


# dụng cụ test tạo kèm BOM: hợp cả loại bộ hấp và plasma (FR-M1-03.3), dùng chung được giữa các loại bộ
BOM_INSTRUMENT_METHODS = ("Steam 134", "Plasma")


def _ensure_bom_instruments(lines):
	for instrument, _qty in lines:
		make_instrument(instrument, methods=BOM_INSTRUMENT_METHODS)


def make_bom(set_type, lines, version=1, effective_from=None, reason=None, legacy=False):
	"""Tạo phiên bản BOM `version` (phải = phiên bản mới nhất + 1) cho loại bộ; trả list Set BOM Item theo `lines`.

	lines: [(mã dụng cụ, số lượng), …]; position = thứ tự trong list (từ 1). Dụng cụ chưa có được tạo với phương pháp
	Hấp 134 °C + Plasma (hợp mọi loại bộ). Mặc định đi qua ``bom_versions.create_version`` (luật dòng, ngày hiệu lực, Audit) với
	``effective_from`` = hôm nay và lý do ``Test BOM version N``. ``legacy=True``: ghi thẳng dòng (cờ dịch vụ, bỏ luật
	dòng) để giả lập dữ liệu có trước FEAT-015, vd dụng cụ không tương thích đã nằm trong BOM.
	"""
	set_type = _ref_name(set_type)
	_ensure_bom_instruments(lines)
	latest = int(
		frappe.db.sql(
			"select ifnull(max(bom_version), 0) from `tabSet BOM Item` where set_type = %s", set_type
		)[0][0]
	)
	if version != latest + 1:
		frappe.throw(f"make_bom: BOM version {version} must follow the latest version {latest} of {set_type}")
	day = getdate(effective_from or today())
	reason = reason or f"Test BOM version {version}"
	if legacy:
		for position, (instrument, qty) in enumerate(lines, 1):
			doc = frappe.get_doc(
				{
					"doctype": "Set BOM Item",
					"set_type": set_type,
					"bom_version": version,
					"instrument": instrument,
					"qty": qty,
					"position": position,
					"effective_from": day,
					"change_reason": reason,
					"based_on_version": latest,
				}
			)
			doc.flags.tc_bom = True
			doc.insert()
	else:
		bom_versions.create_version(
			set_type, [{"instrument": code, "qty": qty} for code, qty in lines], day, reason, latest
		)
	names = dict(
		frappe.get_all(
			"Set BOM Item",
			filters={"set_type": set_type, "bom_version": version},
			fields=["instrument", "name"],
			as_list=True,
		)
	)
	return [frappe.get_doc("Set BOM Item", names[instrument]) for instrument, _qty in lines]


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


def full_count_lines(set_unit):
	"""Dòng kiểm đếm đủ theo BOM đã ghim cho chu trình hiện hành của bộ (mỗi dòng đã đếm, đủ số lượng); chưa ghim → []."""
	unit = frappe.db.get_value(
		"Set Unit", _ref_name(set_unit), ["set_type", "cycle_bom_version"], as_dict=True
	)
	if not int(unit.cycle_bom_version or 0):
		return []
	rows = frappe.get_all(
		"Set BOM Item",
		filters={"set_type": unit.set_type, "bom_version": int(unit.cycle_bom_version)},
		fields=["instrument", "qty"],
		order_by="position asc, name asc",
	)
	return [{"instrument": row.instrument, "counted": 1, "actual_qty": int(row.qty)} for row in rows]


def make_assembly_record(
	set_unit, result="Pass", submit=True, notes=None, lines="auto", shortage_confirmed=False, **fields
):
	"""Tạo Assembly Record cho chu trình hiện hành của bộ; ghi sổ mặc định → ghi cổng T3.

	`lines`: ``"auto"`` → đếm đủ mọi dòng BOM đã ghim (`full_count_lines`); danh sách dòng → dùng nguyên; `fields` ghi
	đè trường khác (``station``, ``branch``…). `shortage_confirmed`: R02 đã xác nhận thiếu (qua cờ dịch vụ, không PIN).
	"""
	doc = frappe.get_doc(
		{
			"doctype": "Assembly Record",
			"set_unit": _ref_name(set_unit),
			"result": result,
			"notes": notes,
			"lines": full_count_lines(set_unit) if lines == "auto" else lines,
			**fields,
		}
	).insert()
	if shortage_confirmed:
		doc.flags.tc_assembly = True
		doc.update(
			{
				"shortage_confirmed": 1,
				"shortage_reason": "Test: R02 xác nhận thiếu",
				"shortage_confirmed_by": "Administrator",
				"shortage_confirmed_at": now_datetime(),
			}
		)
		doc.save()
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
	daily_tested=True,
	**kwargs,
):
	"""Tạo Equipment (mã TB-#### do hệ thống sinh). `kwargs` ghi đè bất kỳ trường nào.

	`daily_tested` (mặc định bật, FEAT-040): ghi sẵn test hằng ngày Đạt của hôm nay cho loại máy cần test, để máy dùng được
	ngay; test về chính test hằng ngày truyền `daily_tested=False`.
	"""
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
	doc = frappe.get_doc(values).insert()
	if daily_tested:
		record_daily_tests(doc)
	return doc


def record_daily_tests(equipment):
	"""Ghi test hằng ngày Đạt của hôm nay cho mọi test bắt buộc của máy (không qua dịch vụ, không khóa/mở máy)."""
	from tracecore.equipment import daily_test

	for test_type in daily_test.required_tests(equipment.equipment_type):
		row = frappe.get_doc(
			{
				"doctype": "Daily Test",
				"equipment": equipment.name,
				"test_type": test_type,
				"result": "Pass",
				"test_date": today(),
				"lot": "TEST-LOT",
				"lot_expiry": add_days(today(), 30),
				"tested_at": now_datetime(),
			}
		)
		row.flags.tc_daily_test = True
		row.insert(ignore_permissions=True)


def make_maintenance_record(equipment, record_type="Preventive", **kwargs):
	"""Tạo Maintenance Record Nháp (FEAT-039). `kwargs` ghi đè bất kỳ trường nào (parts, affected_loads, cost, ...)."""
	values = {
		"doctype": "Maintenance Record",
		"equipment": equipment,
		"record_type": record_type,
		"planned_date": today(),
		**kwargs,
	}
	return frappe.get_doc(values).insert()


def cost_allocation(target, percent=100, target_type="Equipment"):
	"""Một dòng `Cost Allocation` (FEAT-044) cho `make_cost_entry`."""
	return {"target_type": target_type, "target": target, "percent": percent}


def make_cost_entry(**kwargs):
	"""Tạo Cost Entry Nháp (FEAT-044): khoản Điện 1.000.000 đ, kỳ là tháng hiện tại. `kwargs` ghi đè bất kỳ trường nào."""
	values = {
		"doctype": "Cost Entry",
		"category": "Electricity Expense",
		"amount": 1000000,
		"period_from": get_first_day(today()),
		"period_to": get_last_day(today()),
		"source": "Invoice",
		**kwargs,
	}
	return frappe.get_doc(values).insert()


LINEN_STATION = "TR-LIN"


def make_linen_station():
	"""Khu Linen và trạm đồ vải `TR-LIN` (bước LIN, FEAT-033); không có trong dữ liệu khởi tạo, R10 tạo trên Desk."""
	if not frappe.db.exists("Zone Station", LINEN_STATION):
		zone = frappe.get_doc(
			{"doctype": "Zone Station", "zone_station_name": "Linen zone", "is_zone": 1, "zone_type": "Linen"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Zone Station",
				"is_zone": 0,
				"is_active": 1,
				"zone_station_name": "Linen collection",
				"parent_zone": zone.name,
				"station_step": "LIN",
			}
		).insert(ignore_permissions=True, set_name=LINEN_STATION)
	return LINEN_STATION


def make_linen_type(type_name=None, std_weight_kg=0.5, **kwargs):
	"""Tạo Linen Type (FEAT-033): mặc định 0,5 kg/chiếc, tên ngẫu nhiên để không trùng giữa các test."""
	values = {
		"doctype": "Linen Type",
		"type_name": type_name or "Test linen " + frappe.generate_hash(length=6),
		"std_weight_kg": std_weight_kg,
		**kwargs,
	}
	return frappe.get_doc(values).insert()


def linen_line(linen_type, qty=10, weight_kg=5, **kwargs):
	"""Một dòng `Linen Collection Line` (FEAT-033) cho `make_linen_collection`."""
	return {"linen_type": linen_type, "qty": qty, "weight_kg": weight_kg, **kwargs}


def make_linen_collection(lines=None, submit=False, **kwargs):
	"""Tạo Linen Collection Nháp (FEAT-033): một dòng 10 chiếc/5 kg của loại mới; `submit=True` ghi sổ."""
	if lines is None:
		lines = [linen_line(make_linen_type().name)]
	values = {
		"doctype": "Linen Collection",
		"department": make_department(),
		"delivered_by": "Hộ lý khoa",
		"lines": lines,
		**kwargs,
	}
	doc = frappe.get_doc(values).insert()
	return doc.submit() if submit else doc


def make_linen_issue(lines=None, department=None, kind="Return", submit=False, **kwargs):
	"""Tạo Linen Issue Nháp (FEAT-035). Cấp (Return/New) có người nhận ký thẻ; Dispose có lý do và ảnh. `submit=True` ghi sổ.

	`lines` mặc định một dòng 10 chiếc/5 kg của loại mới (tên ngẫu nhiên).
	"""
	if lines is None:
		lines = [linen_line(make_linen_type().name)]
	values = {
		"doctype": "Linen Issue",
		"kind": kind,
		"department": department or make_department(),
		"lines": lines,
	}
	if kind == "Dispose":
		values.update({"reason": "Rách không sửa được", "evidence": "/files/linen-damaged.png"})
	else:
		values.update({"recipient": make_employee().name, "sign_method": "Card"})
	doc = frappe.get_doc({**values, **kwargs}).insert()
	return doc.submit() if submit else doc


def rate_line(rate, rate_type="Item", item=None):
	"""Một dòng `Cost Rate Line` (FEAT-045) cho `make_cost_rate_version`."""
	return {"rate_type": rate_type, "item": item, "rate": rate}


def norm_line(pack_type, item, qty):
	"""Một dòng `Cost Norm Line` (định mức theo loại gói, FEAT-045 A-48 D1)."""
	return {"pack_type": pack_type, "item": item, "qty_per_pack": qty}


def make_cost_rate_version(effective_from=None, rates=None, pack_norms=None, submit=False, **kwargs):
	"""Tạo Cost Rate Version Nháp (FEAT-045): mặc định hiệu lực từ hôm nay, một dòng điện 3.000 đ/kWh.

	`submit=True` ghi sổ (= R01 duyệt) bằng user hiện tại. `kwargs` ghi đè bất kỳ trường nào.
	"""
	values = {
		"doctype": "Cost Rate Version",
		"version_label": "Bảng giá " + frappe.generate_hash(length=6),
		"effective_from": effective_from or today(),
		"rates": rates if rates is not None else [rate_line(3000, "Electricity")],
		"pack_norms": pack_norms or [],
		**kwargs,
	}
	doc = frappe.get_doc(values).insert()
	if submit:
		doc.submit()
	return doc


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


def make_wash_ready_set(**kwargs):
	"""Bộ đã qua cổng T1 trong chu trình mới (đủ điều kiện nạp lô rửa T2), thay cho Dirty Receipt của FEAT-019."""
	unit = make_set_unit(**kwargs)
	make_cycle(unit, passed=("T1",))
	return unit.reload()


def make_wash_machine(**kwargs):
	"""Máy rửa khử khuẩn một cửa ở khu bẩn (serial duy nhất mỗi lần gọi); `kwargs` ghi đè trường Equipment."""
	values = {
		"name": "Máy rửa test",
		"equipment_type": "Washer-Disinfector",
		"serial": "WM-" + frappe.generate_hash(length=8),
		"zone_in": "ZONE-DIRTY",
		"zone_out": None,
		**kwargs,
	}
	return make_equipment(**values)


def make_wash_program(equipment, chemical=None, **kwargs):
	"""Chương trình rửa đầy đủ định mức cho máy `equipment`, mã duy nhất mỗi lần gọi; `chemical` là Item hóa chất."""
	values = {
		"code": "MR-" + frappe.generate_hash(length=6).upper(),
		"minutes": 52,
		"kwh": 3,
		"water": 80,
		"chemical": chemical,
		**kwargs,
	}
	return make_program(equipment, **values)


def make_chemical_batch(item_code="HC-ENZ-01", batch_id=None, expiry_days=60, qty=10):
	"""Lô hóa chất rửa (Item nhóm Chemical) hạn `expiry_days` ngày kể từ hôm nay, còn tồn `qty`.

	`qty = 0` chỉ tạo Batch không có tồn. Lô đã quá hạn (`expiry_days < 0`) cũng chỉ tạo Batch: phiếu nhập kho chặn
	lô quá hạn, mà dữ liệu cũ vẫn có thể còn trong sổ.
	"""
	make_item(item_code, "Chemical", has_batch_no=1, apply_rules=True)
	batch_id = batch_id or f"{item_code}-{frappe.generate_hash(length=6)}"
	expiry = add_days(today(), expiry_days)
	if qty <= 0 or expiry_days < 0:
		return make_batch(item_code, batch_id, expiry)
	make_receipt(
		[{"item_code": item_code, "batch_id": batch_id, "expiry_date": expiry, "qty": qty, "rate": 1000}],
		supplier=make_supplier(),
		document_no="DOC-" + frappe.generate_hash(length=8),
	)
	return frappe.get_doc("Batch", batch_id)


def make_employee(card=None, department=None, first_name="Wash Test", **fields):
	"""Employee HRMS có thẻ đã bật (như `v1/tests/station_fixtures.make_station_employee`, không gắn User).

	`department`: khoa (Department) của nhân viên, cần cho người giao ở T1 (FEAT-019) và người nhận cấp phát T7;
	`fields` ghi đè trường khác.
	"""
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first_name,
			"department": department,
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": today(),
			"company": "_Test Company",
			"status": "Active",
			"tc_card_id": card or "WT-" + frappe.generate_hash(length=10),
			"tc_card_enabled": 1,
			**fields,
		}
	).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)


def make_wash_batch(equipment, program, sets, operator="HR-EMP-TEST", **fields):
	"""Wash Batch `Running` dựng thẳng (không qua dịch vụ nạp) để test quy tắc đọc; operator là mã giả, không kiểm link."""
	doc = frappe.get_doc(
		{
			"doctype": "Wash Batch",
			"batch_type": "Machine",
			"equipment": _ref_name(equipment),
			"program": _ref_name(program),
			"operator": operator,
			"started_at": now_datetime(),
			"set_units": [{"set_unit": _ref_name(unit)} for unit in sets],
			**fields,
		}
	)
	doc.flags.tc_washing = True
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True)


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
	if not frappe.db.exists("Stock Entry Type", "Material Issue"):
		frappe.get_doc(
			{"doctype": "Stock Entry Type", "name": "Material Issue", "purpose": "Material Issue"}
		).insert(ignore_permissions=True)
	return {"company": STOCK_COMPANY, "warehouse": f"Stores - {STOCK_ABBR}"}


def use_stock_company(case):
	"""Company mặc định = Company thử của kho trong suốt test `case`.

	Site test chung có thể đã có Company mặc định khác (test record của ERPNext, vd "Wind Power LLC") nên nhập kho
	theo Company mặc định sẽ chê kho ``Stores - TCT`` "thuộc Company khác". Test cần Company khác tự patch lồng bên trong.
	"""
	from unittest.mock import patch

	patcher = patch("erpnext.get_default_company", return_value=STOCK_COMPANY)
	patcher.start()
	case.addCleanup(patcher.stop)


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


def make_pack_type(name="Giấy crepe", shelf_life_days=30, disabled=0):
	"""Item loại gói (nhóm Packaging) có hạn lưu `shelf_life_days`; trả mã Item `VT-GOI-<tên không dấu>`.

	Gọi lại với hạn lưu/cờ ngừng dùng khác thì cập nhật Item đó (không giữ giá trị cũ một cách âm thầm).
	"""
	item = make_item(f"VT-GOI-{_slug(name)}", "Packaging", shelf_life_days=shelf_life_days)
	if item.tc_shelf_life_days != shelf_life_days or int(item.disabled or 0) != int(disabled):
		item.tc_shelf_life_days = shelf_life_days
		item.disabled = int(disabled)
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


def make_t4_ready_set(
	method="Steam", bom=(("KC-01", 2), ("KC-02", 1)), with_printer=True, short=None, **set_kwargs
):
	"""Bộ sẵn sàng đóng gói tại T4 (TR-004): đã qua T1..T3 Đạt trong chu trình 1.

	Loại bộ mới (mã `T4NNNN`, GTIN test, BOM phiên bản 1 = `bom`, loại gói mặc định `make_pack_type()`
	30 ngày), lô chỉ thị loại 5 đúng phương pháp, và (nếu `with_printer`) máy in tại TR-004 đang lắp nhãn
	đúng phương pháp. `set_kwargs`: khóa của loại bộ (`type_code, set_type_name, gtin, shelf_life_days,
	tray_image`) đi vào `make_set_type`, còn lại (`max_cycles, is_loaner, department`…) vào `make_set_unit`.
	`set_type_department`: khoa của loại bộ; None (mặc định) → loại bộ không có khoa như dữ liệu có trước FEAT-015
	(patch không bịa khoa), để các kỳ vọng T4 của FEAT-018 (nhãn không có khoa khi bộ không có khoa) giữ nguyên.
	`short`: ``{mã dụng cụ: số lượng thực tế}`` → phiếu lắp ráp T3 có các dòng đó thiếu và R02 đã xác nhận (FEAT-020);
	`instruments` chỉ gồm các mã không thiếu (những mã T4 phải tick).
	Trả `frappe._dict(set_id, set_type, gtin, pack_type, ci_batch, printer, instruments)`.
	"""
	type_kwargs = {key: set_kwargs.pop(key) for key in _SET_TYPE_KWARGS if key in set_kwargs}
	set_type_department = set_kwargs.pop("set_type_department", None)
	pack_type = make_pack_type()
	set_type = make_set_type(
		type_kwargs.pop("type_code", None) or _free_type_code(),
		method=method,
		default_pack_type=pack_type,
		department=set_type_department or "auto",
		**type_kwargs,
	)
	if not set_type_department:
		# khoa bắt buộc khi lưu từ FEAT-015; ghi thẳng DB để giả lập loại bộ cũ chưa có khoa
		frappe.db.set_value("Instrument Set Type", set_type.name, "department", None, update_modified=False)
		set_type.department = None
	if bom:  # bom rỗng: loại bộ chưa có BOM (dữ liệu cũ) để kiểm T4 chặn BOM rỗng
		make_bom(set_type, bom)
	set_unit = make_set_unit(set_type.name, **set_kwargs)
	if short:
		make_cycle(set_unit, passed=("T1", "T2"))
		counted = [
			{**row, "actual_qty": short.get(row["instrument"], row["actual_qty"])}
			for row in full_count_lines(set_unit)
		]
		make_assembly_record(set_unit, lines=counted, shortage_confirmed=True)
	else:
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
		instruments=[code for code, _qty in bom if code not in (short or {})],
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


T6_STATION = "TR-006"
ALL_GATES = ("T1", "T2", "T3", "T4", "T5")


def make_sterile_location(location_name="Kệ test", zone_station=T6_STATION, **fields):
	"""Kệ kho vô khuẩn `KE-####` thuộc trạm T6 (FEAT-025)."""
	return frappe.get_doc(
		{
			"doctype": "Sterile Location",
			"location_name": location_name,
			"zone_station": zone_station,
			**fields,
		}
	).insert()


def make_released_pack(status="Released", expiry_days=30, passed=ALL_GATES, set_type=None, **fields):
	"""Gói đã giải phóng sẵn sàng nhập kho T6, thay cho luồng T5b (FEAT-023, quyết định D2 của FEAT-025).

	Bộ mới (hoặc cùng loại `set_type`) đi qua các cổng `passed` bằng `step_gate` (đủ năm cổng = Vô khuẩn); Pack
	ghi sổ ở trạng thái `status` (mặc định Released), hạn `today() + expiry_days` (âm = đã quá hạn). `fields` ghi
	đè trường Pack. Trả Pack.
	"""
	set_unit = make_set_unit(set_type)
	make_cycle(set_unit, passed=passed)
	cycle_no = frappe.db.get_value("Set Unit", set_unit.name, "current_cycle_no")
	pack = make_pack(
		set_unit,
		status=status,
		cycle_no=cycle_no,
		expiry=add_days(today(), expiry_days),
		**fields,
	)
	if not code_registry.is_issued(pack.name):  # như packing.generate: Cycle ID nằm trong Code Registry
		code_registry.register(pack.name, code_registry.CYCLE_PREFIX, "Pack", pack.name)
	step_gate.bind_cycle(set_unit.name, pack.name, None)
	return pack


T7_STATION = "TR-007"


def make_stocked_pack(set_type=None, expiry_days=30, location=None):
	"""Gói Trong kho vô khuẩn sẵn sàng cấp phát T7 (FEAT-026): gói giải phóng rồi nhập kệ bằng dịch vụ kho T6.

	Hạn đặt lại thành hôm nay + `expiry_days` sau khi nhập kho (âm = đã quá hạn mà job 00:00 chưa chạy). Trả Pack.
	"""
	from tracecore.reprocessing import storage

	pack = make_released_pack(set_type=set_type)
	shelf = location or make_sterile_location("Kệ cấp phát")
	storage.putaway(pack.name, getattr(shelf, "name", shelf), T6_STATION)
	frappe.db.set_value("Pack", pack.name, "expiry", add_days(today(), expiry_days), update_modified=False)
	return frappe.get_doc("Pack", pack.name)


def make_sterilizer(equipment_type="Steam Sterilizer", capacity=None, **kwargs):
	"""Máy tiệt khuẩn hai cửa khu sạch → vô khuẩn (serial duy nhất mỗi lần gọi); `capacity` là Data (Q4 A-16)."""
	values = {
		"name": "Máy tiệt khuẩn test",
		"equipment_type": equipment_type,
		"serial": "ST-" + frappe.generate_hash(length=8),
		"zone_in": "ZONE-CLEAN",
		"zone_out": "ZONE-STERILE",
		"capacity": capacity,
		**kwargs,
	}
	return make_equipment(**values)


def make_sterilize_program(equipment, pack_types=(), **kwargs):
	"""Chương trình tiệt khuẩn đủ định mức cho máy `equipment`, mã duy nhất mỗi lần gọi.

	`pack_types`: danh sách Item loại gói tương thích (rỗng = chương trình không giới hạn loại gói).
	"""
	values = {
		"code": "MH-" + frappe.generate_hash(length=6).upper(),
		"minutes": 4,
		"kwh": 3.5,
		"water": 20,
		**kwargs,
	}
	if pack_types:
		values["compatible_pack_types"] = [{"pack_type": _ref_name(item)} for item in pack_types]
	return make_program(equipment, **values)


def make_load_ready_pack(
	method="Steam", expiry_days=30, passed=("T1", "T2", "T3", "T4"), set_type=None, **fields
):
	"""Gói `Packed` sẵn sàng nạp mẻ tại T5 (FEAT-022): bộ mới qua các cổng `passed`, Pack ghi sổ, Cycle ID hiện hành.

	Loại bộ mới theo `method` (`Steam`/`Plasma`) trừ khi truyền `set_type` (mã loại bộ có sẵn, dữ liệu demo); `fields`
	ghi đè trường Pack (vd `pack_type`, `status`). Dựng thẳng bằng `step_gate` thay cho T1 đến T4 thật. Trả Pack.
	"""
	set_type = (
		frappe.get_doc("Instrument Set Type", set_type)
		if set_type
		else make_set_type(_free_type_code("T5"), method=method)
	)
	set_unit = make_set_unit(set_type.name)
	make_cycle(set_unit, passed=passed)
	cycle_no = frappe.db.get_value("Set Unit", set_unit.name, "current_cycle_no")
	pack = make_pack(set_unit, cycle_no=cycle_no, expiry=add_days(today(), expiry_days), **fields)
	if not code_registry.is_issued(pack.name):  # như packing.generate: Cycle ID nằm trong Code Registry
		code_registry.register(pack.name, code_registry.CYCLE_PREFIX, "Pack", pack.name)
	step_gate.bind_cycle(set_unit.name, pack.name, None)
	return pack


def make_load(equipment, program, packs, operator="HR-EMP-TEST", **fields):
	"""Sterilization Load `Running` dựng thẳng (không qua dịch vụ nạp) để test quy tắc đọc; operator là mã giả."""
	now = now_datetime()
	doc = frappe.get_doc(
		{
			"doctype": "Sterilization Load",
			"equipment": _ref_name(equipment),
			"program": _ref_name(program),
			"operator": operator,
			"started_at": now,
			"load_completed_at": now,
			"packs": [
				{
					"pack": _ref_name(pack),
					"set_unit": frappe.db.get_value("Pack", _ref_name(pack), "set_unit"),
				}
				for pack in packs
			],
			**fields,
		}
	)
	doc.flags.tc_sterilizing = True
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	for pack in packs:
		frappe.db.set_value("Pack", _ref_name(pack), {"status": "In Load", "load": doc.name})
	return doc


def make_bom_set_type(type_code, lines, caps=None):
	"""Loại bộ cùng BOM v1; ``caps``: ``{mã dụng cụ: cơ số}`` (thiếu = Chưa xác định)."""
	for code, _qty in lines:
		make_instrument(code, methods=BOM_INSTRUMENT_METHODS, max_cycles=(caps or {}).get(code))
	return make_set_type(type_code, bom=lines)


def make_par_level(target_doctype, target, par_kind="Reprocessing", **values):
	"""Tạo Par Level (FEAT-031); ``values``: max_cycles, source, department, min_qty, max_qty, over_percent…"""
	return frappe.get_doc(
		{
			"doctype": "Par Level",
			"par_kind": par_kind,
			"target_doctype": target_doctype,
			"target": target,
			**values,
		}
	).insert()


WASTE_STATION = "TR-WST"
WASTE_PACKAGING = "VT-TUI-VANG"


def make_waste_station():
	"""Khu Waste và trạm thu gom `TR-WST` (bước WST, FEAT-047); không có trong dữ liệu khởi tạo, R10 tạo trên Desk."""
	if not frappe.db.exists("Zone Station", WASTE_STATION):
		zone = frappe.get_doc(
			{"doctype": "Zone Station", "zone_station_name": "Waste zone", "is_zone": 1, "zone_type": "Waste"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Zone Station",
				"is_zone": 0,
				"is_active": 1,
				"zone_station_name": "Waste collection",
				"parent_zone": zone.name,
				"station_step": "WST",
			}
		).insert(ignore_permissions=True, set_name=WASTE_STATION)
	return WASTE_STATION


def make_waste_type(type_name=None, waste_group="Sharp Infectious", std_weight_kg=2, **kwargs):
	"""Loại chất thải hợp lệ; bao bì là Item có sẵn của test (không kiểm Link để không phụ thuộc Item Group)."""
	doc = frappe.get_doc(
		{
			"doctype": "Waste Type",
			"type_name": type_name or "Waste " + frappe.generate_hash(length=8),
			"waste_group": waste_group,
			"packaging": WASTE_PACKAGING,
			"std_weight_kg": std_weight_kg,
			"max_storage_hours": 48,
			"is_active": 1,
			**kwargs,
		}
	)
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True)


def make_waste_container():
	"""Một túi `Waste Container` (dịch vụ mới được tạo: cờ `tc_waste`); dùng ở test NC của M2."""
	doc = frappe.get_doc(
		{
			"doctype": "Waste Container",
			"waste_type": make_waste_type().name,
			"weight_kg": 1,
			"status": "Held",
			"collected_at": now_datetime(),
		}
	)
	doc.flags.tc_waste = True
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True, set_name="CT-261030-" + frappe.generate_hash(length=5)).name

