"""Dữ liệu demo cho site dev/test (developer_mode hoặc allow_tests; không chạy trên production).

- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_demo_set`` in Set ID GIAI thử để quét ở /app/station.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_t4_demo`` chuẩn bị màn T4 đóng gói (SCR-08) tại
  TR-004 và in JSON các mã để quét (bộ hấp, bộ plasma, bộ chưa qua cổng T3, lô chỉ thị, mã cuộn nhãn, máy in).
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_equipment_demo`` chuẩn bị máy và chương trình xử lý
  cho e2e Desk SCR-21 (FEAT-038) và in JSON các mã (tên máy, mã chương trình).
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_codes_demo`` chuẩn bị máy in mạng demo và đối tượng
  để e2e Desk in nhãn QR (SCR-33, FEAT-005) và in JSON các mã.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_instrument_demo`` chuẩn bị nhóm, dụng cụ, loại bộ và bộ
  demo cho e2e Desk danh mục dụng cụ (SCR-01, FEAT-014) và in JSON các mã.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_inventory_demo`` chuẩn bị Company, kho, nhà cung cấp và
  bốn vật tư mẫu (chỉ thị hóa học lớp 5, chỉ thị sinh học, bao gói, hóa chất) cho e2e Desk nhập kho (SCR-24, FEAT-041).
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_set_type_demo`` chuẩn bị loại gói, dụng cụ, loại bộ có
  nhiều phiên bản BOM, ảnh bộ đã xếp và bộ đang giữa chu trình cho e2e Desk loại bộ (SCR-02, FEAT-015) và in JSON các mã.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_t6_demo`` chuẩn bị màn T6 kho vô khuẩn (SCR-11) tại
  TR-006: hai kệ ``KE-``, gói đã giải phóng, gói chưa giải phóng, gói trong kho, gói sắp hết hạn; in JSON các mã.
"""

import io
import json
import os
import secrets
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

from tracecore.core import code_registry, gs1, step_gate
from tracecore.core import print as core_print
from tracecore.equipment import status as equipment_status
from tracecore.instrument import bom, bom_versions
from tracecore.setup.label_templates import ensure_object_templates, ensure_sample_templates
from tracecore.tests import factories

DEMO_SET_TYPE = "DEMO"

# --- Demo T4 (FEAT-018) ------------------------------------------------------------------------------
T4_STATION = "TR-004"
T4_PRINTER_NAME = "DEMO-T4 printer"
# Mã loại bộ chỉ gồm 2-8 chữ hoa/số (nằm trong GIAI) nên không có gạch nối: DEMOT4S/DEMOT4P
T4_SET_TYPES = {"Steam": "DEMOT4S", "Plasma": "DEMOT4P"}
T4_GTIN_FIRST_SERIAL = 90001  # dải GTIN test riêng cho demo, không đụng serial cố định (1…) của test
T4_LUBE_INSTRUMENT = "DEMO-T4-KC-02"
T4_LUBE_INTERVAL = 50
T4_INSTRUMENT_SPAULDING = "Critical"
T4_INSTRUMENT_METHODS = {"Steam": ("Steam 134",), "Plasma": ("Plasma",)}
DEMO_OIL_LOT = "DEMO-T4-DAU-01"  # lô dầu để xác nhận "Đã bảo dưỡng" cho nhắc tra dầu
STEAM_LABEL, PLASMA_LABEL = (code for code, _method in factories.LABEL_ITEMS)
T4_GATES_READY = ("T1", "T2", "T3")
T4_GATES_FAIL = ("T1", "T2")  # chưa có cổng T3 Đạt → T4 từ chối GATE_PREV_NOT_PASSED


def _require_dev_site():
	if not (frappe.conf.get("developer_mode") or frappe.conf.get("allow_tests") or frappe.flags.in_test):
		frappe.throw(_("Demo data can only be created on a developer or test site."))


@contextmanager
def _temporary_r10():
	"""Give Administrator explicit R10 while demo accounts are created, then restore exactly.

	Never commit inside this block: temporary authority must not be persisted.
	"""
	admin = frappe.get_doc("User", "Administrator")
	had_r10 = any(row.role == "TC R10" for row in admin.roles)
	try:
		if not had_r10:
			admin.add_roles("TC R10")
		yield
	finally:
		if not had_r10:
			admin.remove_roles("TC R10")


def _enroll_otp(user):
	"""Enroll a demo account in native OTP App authentication; returns its (stable) secret."""
	import pyotp
	from frappe.twofactor import get_default, set_default
	from frappe.utils.password import decrypt, encrypt

	key = user + "_otpsecret"
	stored = get_default(key)
	secret = decrypt(stored) if stored else pyotp.random_base32()
	if not stored:
		set_default(key, encrypt(secret))
	set_default(user + "_otplogin", 1)
	return secret


def _require_administrator():
	if frappe.session.user != "Administrator":
		frappe.throw(_("Only Administrator can prepare demo accounts."), frappe.PermissionError)


def ensure_e2e_users(station, t4_station, password, r10_password):
	"""CLI dev/test bootstrap; returned secrets must go only to the private E2E env file.

	Enroll generated demo accounts in native OTP App authentication, avoiding email
	delivery without disabling 2FA. Never commit while temporary authority is held.
	"""
	from tracecore.setup import provision

	_require_dev_site()
	_require_administrator()
	with _temporary_r10():
		result = {
			"user": provision.station_user(station, password),
			"t4_user": provision.station_user(t4_station, password),
			"r10_user": provision.desk_user("TC R10", "r10-e2e", r10_password),
		}
		for prefix in ("", "t4_", "r10_"):
			result[prefix + "otp_secret"] = _enroll_otp(result[prefix + "user"])
	return result


def ensure_desk_users(password, specs):
	"""Dev/test Desk accounts for e2e whose role needs 2FA (R01/R02/R09/R10).

	``specs`` is a list of ``{"key", "role", "name", "extra_roles"}``; returns ``<key>_user`` and
	``<key>_otp_secret`` for each. Secrets go only to the private E2E env file.
	"""
	from tracecore.setup import provision

	_require_dev_site()
	_require_administrator()
	result = {}
	with _temporary_r10():
		for spec in specs:
			user = provision.desk_user(spec["role"], spec["name"], password)
			for role in spec.get("extra_roles") or ():
				provision.desk_user(role, spec["name"], password)
			result[spec["key"] + "_user"] = user
			result[spec["key"] + "_otp_secret"] = _enroll_otp(user)
	return result


def ensure_station_demo(station, user, card_id=None, second_station=None):
	"""Dev/test-only card identity for an existing kiosk User; no password or PIN is seeded.

	Cards are generated once and reused. Expired demo competencies are renewed in place;
	valid competencies and their dates remain unchanged on a repeated preparation run.
	"""
	from tracecore.core.station_auth import normalize_card_id

	_require_dev_site()
	stations = list(dict.fromkeys(filter(None, (station, second_station))))
	for target in stations:
		if not frappe.db.exists("Zone Station", {"name": target, "is_zone": 0, "is_active": 1}):
			frappe.throw(_("An active station is required for demo data."))
	if not frappe.db.get_value("User", user, "enabled"):
		frappe.throw(_("An enabled user is required for demo data."))
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if not company:
		frappe.throw(_("Complete company setup before creating demo employees."))
	name = frappe.db.get_value("Employee", {"user_id": user}, "name")
	employee = (
		frappe.get_doc("Employee", name)
		if name
		else frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "TraceCore Demo",
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": today(),
				"company": company,
				"user_id": user,
			}
		)
	)
	employee.status = "Active"
	employee.tc_card_enabled = 1
	employee.tc_card_id = normalize_card_id(card_id or employee.tc_card_id or f"E2E-{secrets.token_hex(12)}")
	employee.save(ignore_permissions=True)
	now = now_datetime()
	for target in stations:
		name = frappe.db.get_value(
			"Station Competency", {"employee": employee.name, "station": target}, "name"
		)
		competency = (
			frappe.get_doc("Station Competency", name)
			if name
			else frappe.get_doc(
				{
					"doctype": "Station Competency",
					"employee": employee.name,
					"station": target,
				}
			)
		)
		if (
			not name
			or not competency.is_active
			or not (competency.valid_from <= now <= competency.valid_until)
		):
			competency.update(
				{"valid_from": add_days(now, -1), "valid_until": add_days(now, 365), "is_active": 1}
			)
			competency.save(ignore_permissions=True)
	result = {"employee": employee.name, "card_id": employee.tc_card_id}
	print(json.dumps(result, sort_keys=True))
	return result


def ensure_demo_set():
	"""Tạo (nếu chưa có) loại bộ DEMO và một Set Unit; trả và in Set ID."""
	_require_dev_site()
	if not frappe.db.exists("Instrument Set Type", DEMO_SET_TYPE):
		doc = frappe.get_doc(
			{
				"doctype": "Instrument Set Type",
				"type_code": DEMO_SET_TYPE,
				"set_type_name": "Demo set",
				"method": "Steam",
				"department": _demo_department(),
				"default_pack_type": _ensure_pack_type(_t4_catalog()["Steam"]["pack_type"]),
			}
		)
		# loại bộ demo không có BOM (chỉ để in Set ID) như dữ liệu có trước FEAT-015: ghi với cờ dịch vụ BOM
		doc.flags.tc_bom = True
		doc.insert(ignore_permissions=True)
	set_id = frappe.db.get_value("Set Unit", {"set_type": DEMO_SET_TYPE}, "name", order_by="creation asc")
	if not set_id:
		set_id = (
			frappe.get_doc({"doctype": "Set Unit", "set_type": DEMO_SET_TYPE, "max_cycles": 300})
			.insert(ignore_permissions=True)
			.name
		)
	print(set_id)
	return set_id


def _t4_catalog():
	"""Danh mục demo T4; tên hiển thị lấy bản dịch tiếng Việt (vi.csv) để nhãn và màn hình có dấu."""
	return {
		"Steam": {
			"set_name": _("Demo general surgery set", lang="vi"),
			"pack_type": ("DEMO-T4-GOI-CREPE", _("Demo crepe paper", lang="vi"), 30),
			"bom": (
				("DEMO-T4-KC-01", _("Demo straight forceps", lang="vi"), 2),
				(T4_LUBE_INSTRUMENT, _("Demo surgical scissors", lang="vi"), 1),
				("DEMO-T4-KC-03", _("Demo scalpel handle", lang="vi"), 1),
				("DEMO-T4-KC-04", _("Demo kidney dish", lang="vi"), 1),
			),
		},
		"Plasma": {
			"set_name": _("Demo laparoscopic set", lang="vi"),
			"pack_type": ("DEMO-T4-GOI-TYVEK", _("Demo Tyvek pouch", lang="vi"), 180),
			"bom": (
				("DEMO-T4-PL-01", _("Demo laparoscopic grasper", lang="vi"), 1),
				("DEMO-T4-PL-02", _("Demo laparoscopic scissors", lang="vi"), 1),
				("DEMO-T4-PL-03", _("Demo trocar", lang="vi"), 2),
			),
		},
	}


def _demo_png(code):
	"""Ảnh PNG giả của dụng cụ/khay: nền xám nhạt, chữ "DEMO" và mã (không phải ảnh thật)."""
	from PIL import Image, ImageDraw, ImageFont

	image = Image.new("RGB", (256, 256), (223, 230, 238))
	draw = ImageDraw.Draw(image)
	draw.rectangle((4, 4, 251, 251), outline=(59, 74, 90), width=4)
	draw.text((128, 110), "DEMO", fill=(31, 78, 121), font=ImageFont.load_default(size=64), anchor="mm")
	draw.text((128, 180), code, fill=(59, 74, 90), font=ImageFont.load_default(size=20), anchor="mm")
	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	return buffer.getvalue()


def _demo_image(code):
	"""URL File công khai của ảnh demo cho `code` (tạo một lần)."""
	file_name = f"{code.lower()}-demo.png"
	url = frappe.db.get_value("File", {"file_name": file_name, "is_private": 0}, "file_url")
	if url:
		return url
	return (
		frappe.get_doc(
			{"doctype": "File", "file_name": file_name, "content": _demo_png(code), "is_private": 0}
		)
		.insert(ignore_permissions=True)
		.file_url
	)


def _free_demo_gtin():
	used = set(
		frappe.get_all(
			"Instrument Set Type", filters={"gtin": ["like", f"{gs1.TEST_GTIN_PREFIX}%"]}, pluck="gtin"
		)
	)
	for serial in range(T4_GTIN_FIRST_SERIAL, 100000):
		gtin = gs1.make_test_gtin14(serial)
		if gtin not in used:
			return gtin
	frappe.throw("No free demo GTIN-14 left")


def _ensure_instrument(code, name, method):
	"""Dụng cụ demo: Spaulding Thiết yếu, phương pháp theo loại bộ (Steam → Hấp 134 °C, Plasma → Plasma)."""
	methods = T4_INSTRUMENT_METHODS[method]
	if not frappe.db.exists("Instrument", code):
		lube = code == T4_LUBE_INSTRUMENT
		factories.make_instrument(
			code,
			name,
			interval=T4_LUBE_INTERVAL if lube else None,
			maint_type="Lubrication" if lube else None,
			spaulding=T4_INSTRUMENT_SPAULDING,
			methods=methods,
		)
		_ensure_instrument_photo(code)
		return
	doc = frappe.get_doc("Instrument", code)
	if not doc.spaulding_class or not doc.compatible_methods:
		# dụng cụ demo tạo trước FEAT-014: bổ sung dữ liệu demo (không áp cho dữ liệu thật, xem patch)
		doc.spaulding_class = doc.spaulding_class or T4_INSTRUMENT_SPAULDING
		if not doc.compatible_methods:
			doc.set("compatible_methods", [{"method": m} for m in methods])
		doc.save(ignore_permissions=True)
	_ensure_instrument_photo(code)


def _ensure_instrument_photo(code):
	"""Ảnh demo của dụng cụ: File riêng tư đính vào trường ảnh (qua kiểm file) và thumbnail cho T4 (FEAT-014 I11).

	Dụng cụ demo cũ có ảnh công khai (trước FEAT-014) hoặc chưa có thumbnail thì được thay ảnh mới.
	"""
	doc = frappe.get_doc("Instrument", code)
	if doc.image and doc.image_thumbnail:
		return
	photo = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{code.lower()}-photo.png",
			"content": _demo_png(code),
			"is_private": 1,
			"attached_to_doctype": "Instrument",
			"attached_to_name": code,
			"attached_to_field": "image",
		}
	).insert(ignore_permissions=True)
	doc.image = photo.file_url
	doc.save(ignore_permissions=True)


def _demo_department():
	"""Khoa demo sở hữu các loại bộ demo (FEAT-015: khoa của loại bộ bắt buộc); trả tên Department."""
	return factories.make_department(_("Demo operating theatre", lang="vi"))


def _ensure_pack_type(pack_type):
	"""Item loại gói demo ``(mã, tên, hạn lưu)`` (tạo một lần); trả mã Item."""
	pack_code, pack_name, days = pack_type
	if not frappe.db.exists("Item", pack_code):
		factories.make_item(pack_code, "Packaging", shelf_life_days=days)
		frappe.db.set_value("Item", pack_code, "item_name", pack_name)
	return pack_code


def _ensure_set_type(method, spec, code=None, ensure_instruments=True):
	"""Loại bộ demo (khoa demo, GTIN test, loại gói mặc định, ảnh khay) và BOM phiên bản 1; trả mã loại bộ.

	`code` mặc định là loại bộ demo T4 của `method`; `ensure_instruments` False khi dụng cụ của BOM đã được tạo sẵn.
	"""
	code = code or T4_SET_TYPES[method]
	pack_code = _ensure_pack_type(spec["pack_type"])
	if ensure_instruments:
		for instrument, name, _qty in spec["bom"]:
			_ensure_instrument(instrument, name, method)
	lines = [{"instrument": instrument, "qty": qty} for instrument, _name, qty in spec["bom"]]
	if not frappe.db.exists("Instrument Set Type", code):
		# FR-M1-03.1: loại bộ tạo cùng BOM v1 qua dịch vụ BOM (luật dòng, Audit)
		bom_versions.create_set_type(
			{
				"type_code": code,
				"set_type_name": spec["set_name"],
				"method": method,
				"gtin": _free_demo_gtin(),
				"department": _demo_department(),
				"default_pack_type": pack_code,
			},
			lines,
		)
		frappe.db.set_value("Instrument Set Type", code, "tray_image", _demo_image(f"{code}-TRAY"))
	elif not frappe.db.exists("Set BOM Item", {"set_type": code}):
		bom_versions.create_version(code, lines, bom_versions.today(), _("Demo data"), 0)
	return code


def _gate_results(row):
	if not row.current_cycle_no or row.status != "Processing" or row.active_cycle_id:
		return None
	return {gate["step"]: gate["result"] for gate in step_gate.gates(row.name)}


def _matches(results, passed):
	return results is not None and all(
		results[step] == ("Pass" if step in passed else "Pending") for step in ("T1", "T2", "T3", "T4")
	)


def _has_lube_reminder(set_id):
	return bool(
		frappe.db.exists("Instrument Maintenance", {"set_unit": set_id, "instrument": T4_LUBE_INSTRUMENT})
	)


def _ensure_set(set_type, passed, reminder=False):
	"""Set Unit đầu tiên của `set_type` có đúng các cổng `passed` Đạt (còn lại Chưa) và chưa có Cycle ID.

	`reminder` chọn bộ có (True, kèm nhắc tra dầu đến hạn) hoặc không có (False) bản ghi bảo dưỡng tra dầu.

	Không có (vd bộ cũ đã được đóng gói) thì tạo bộ mới và mở chu trình. Trả Set ID.
	"""
	rows = frappe.get_all(
		"Set Unit",
		filters={"set_type": set_type},
		fields=["name", "status", "active_cycle_id", "current_cycle_no"],
		order_by="creation asc",
	)
	for row in rows:
		if _matches(_gate_results(row), passed) and _has_lube_reminder(row.name) == reminder:
			return row.name
	unit = frappe.get_doc({"doctype": "Set Unit", "set_type": set_type, "max_cycles": 300}).insert(
		ignore_permissions=True
	)
	factories.make_cycle(unit.name, passed=passed)
	if reminder:
		_ensure_lube_reminder(unit.name)
	return unit.name


def _ensure_lube_reminder(set_id):
	"""Bộ hấp có nhắc tra dầu đến hạn (cycles_since = ngưỡng, còn hoãn được)."""
	if not frappe.db.exists("Instrument Maintenance", {"set_unit": set_id, "instrument": T4_LUBE_INSTRUMENT}):
		factories.make_maintenance(set_id, T4_LUBE_INSTRUMENT, cycles_since=T4_LUBE_INTERVAL)


def _ensure_roll(label_item):
	code = frappe.db.get_value(
		"Code Registry",
		{
			"prefix": code_registry.ROLL_PREFIX,
			"ref_doctype": "Item",
			"ref_name": label_item,
			"status": "Active",
		},
		"name",
		order_by="creation asc",
	)
	return code or factories.make_roll(label_item)


def _ensure_printer(roll_steam):
	"""Máy in duy nhất đang hoạt động của TR-004: nạp nhãn hấp, host trống, không hỗ trợ Unicode."""
	name = frappe.db.get_value("Printer", {"station": T4_STATION, "printer_name": T4_PRINTER_NAME}, "name")
	if not name:
		name = factories.make_printer(T4_STATION, STEAM_LABEL, host="", name=T4_PRINTER_NAME)
	# đổi cuộn bằng mã quét cần đúng một máy in hoạt động ở trạm
	frappe.db.set_value("Printer", {"station": T4_STATION, "name": ["!=", name]}, "is_active", 0)
	frappe.db.set_value("Printer", name, {"is_active": 1, "host": "", "supports_unicode": 0})
	if frappe.db.get_value("Printer", name, "label_type_loaded") != STEAM_LABEL:
		core_print.set_roll(name, roll_steam)
	return name


def ensure_t4_demo():
	"""Chuẩn bị màn T4 (SCR-08) tại TR-004 trên site dev/test; idempotent, trả và in JSON các mã để quét.

	Tạo nếu thiếu: mẫu nhãn mẫu, loại bộ hấp/plasma có GTIN test và BOM 3-4 dụng cụ (ảnh PNG "DEMO"), loại gói,
	lô chỉ thị loại 5 cho từng phương pháp, lô dầu ``DEMO_OIL_LOT``, Item nhãn và mã cuộn ``CN-`` cho hai loại nhãn,
	máy in tại TR-004 nạp nhãn hấp. Bộ hấp, bộ plasma đã qua T1-T3 và không có nhắc bảo dưỡng; `set_maint` là bộ hấp
	qua T1-T3 có một nhắc tra dầu đến hạn (luồng thay thế của AC-12); một bộ
	hấp khác mới qua T1-T2 (thiếu cổng T3). Bộ đã được đóng gói được thay bằng bộ mới khi gọi lại.
	"""
	_require_dev_site()
	ensure_sample_templates()
	factories.make_label_items()
	set_types = {method: _ensure_set_type(method, spec) for method, spec in _t4_catalog().items()}

	oil_item = factories.make_item("DEMO-T4-DAU", "Lubricant").name
	factories.make_batch(oil_item, DEMO_OIL_LOT, expiry_date=add_days(today(), 365))
	ci = {
		method: factories.make_ci_batch(
			method, "5", expiry_days=365, batch_id=f"DEMO-T4-CI5-{method.upper()}"
		)
		for method in set_types
	}
	rolls = {label: _ensure_roll(label) for label in (STEAM_LABEL, PLASMA_LABEL)}

	result = {
		"set_steam": _ensure_set(set_types["Steam"], T4_GATES_READY),
		"set_maint": _ensure_set(set_types["Steam"], T4_GATES_READY, reminder=True),
		"set_plasma": _ensure_set(set_types["Plasma"], T4_GATES_READY),
		"set_gate_fail": _ensure_set(set_types["Steam"], T4_GATES_FAIL),
		"ci_steam": ci["Steam"],
		"ci_plasma": ci["Plasma"],
		"roll_steam": rolls[STEAM_LABEL],
		"roll_plasma": rolls[PLASMA_LABEL],
		"printer": _ensure_printer(rolls[STEAM_LABEL]),
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo thiết bị và chương trình xử lý (FEAT-038) ---------------------------------------------------
EQ_MANUFACTURER, EQ_MODEL = "E2E Maker", "E2E-1"
EQ_CONSUMABLE = "DEMO-EQ-HOA-CHAT"
EQ_SERIALS = {
	"steam": "E2E-STEAM-001",
	"steam_copy_target": "E2E-STEAM-002",
	"washer": "E2E-WASH-001",
	"retired": "E2E-RETIRED-001",
}
EQ_PROGRAMS = {
	"program_complete": "E2E-STEAM-134",
	"program_missing": "E2E-STEAM-MISS",
	"program_inactive": "E2E-STEAM-OLD",
	"program_outside": "E2E-STEAM-HOT",
}
EQ_STEAM_SAFE_RANGE = {"safe_temp_min": 105, "safe_temp_max": 140, "safe_pressure_max": 3.5}
EQ_WASHER_NORM = {"duration_min": 45, "kwh_per_cycle": 3, "water_l_per_cycle": 60}


def _ensure_equipment(key, **fields):
	"""Máy theo serial cố định (Equipment không xóa được nên dùng lại); trả tên TB-####."""
	serial = EQ_SERIALS[key]
	name = frappe.db.get_value("Equipment", {"serial_no": serial}, "name")
	if name:
		return name
	values = {"manufacturer": EQ_MANUFACTURER, "model": EQ_MODEL, **fields}
	return factories.make_equipment(serial=serial, **values).name


def _ensure_program(key, equipment, **fields):
	code = EQ_PROGRAMS[key]
	if frappe.db.exists("Process Program", code):
		return code
	factories.make_program(equipment, code=code, **fields)
	return code


def ensure_equipment_demo():
	"""Máy và chương trình demo cho e2e Desk thiết bị (SCR-21) trên site dev/test; idempotent, trả và in JSON.

	- ``steam``: máy hấp 2 cửa Sạch → Vô khuẩn (``E2E-STEAM-001``) có dải an toàn 105-140 °C, 3,5 bar và bốn chương
	  trình: đủ định mức, thiếu định mức (không kWh), ngừng dùng, và một chương trình 150 °C (ngoài dải).
	- ``steam_copy_target``: máy hấp cùng hãng + model để thử "Sao chép sang máy khác"; ``retired``: máy cùng model đã
	  ngừng sử dụng (không được hiện trong hộp thoại sao chép); ``washer``: máy rửa 2 cửa Bẩn → Sạch.
	- Một ``Equipment Type Norm`` cho ``Washer-Disinfector``.
	Equipment không xóa được và ``Retired`` là một chiều nên bản ghi được tìm lại theo serial.
	"""
	_require_dev_site()
	consumable = factories.make_item(EQ_CONSUMABLE, "Lubricant").name
	steam = _ensure_equipment("steam", name="E2E steam sterilizer", **EQ_STEAM_SAFE_RANGE)
	target = _ensure_equipment("steam_copy_target", name="E2E steam sterilizer 2")
	washer = _ensure_equipment(
		"washer",
		name="E2E washer",
		equipment_type="Washer-Disinfector",
		manufacturer="E2E Wash Maker",
		model="E2E-W1",
		zone_in="ZONE-DIRTY",
		zone_out="ZONE-CLEAN",
	)
	retired = _ensure_equipment("retired", name="E2E retired steam sterilizer")
	if frappe.db.get_value("Equipment", retired, "status") != "Retired":
		equipment_status.set_status(retired, "Retired", "E2E: demo equipment retired")

	if not frappe.db.exists("Equipment Type Norm", "Washer-Disinfector"):
		frappe.get_doc(
			{"doctype": "Equipment Type Norm", "equipment_type": "Washer-Disinfector", **EQ_WASHER_NORM}
		).insert(ignore_permissions=True)

	line = [{"item": consumable, "qty_per_load": 1}]
	programs = {
		"program_complete": _ensure_program(
			"program_complete", steam, minutes=30, water=20, consumables=line, temperature=134, pressure=3
		),
		"program_missing": _ensure_program(
			"program_missing", steam, minutes=30, kwh=0, water=20, consumables=line, temperature=121
		),
		"program_outside": _ensure_program(
			"program_outside", steam, minutes=30, water=20, consumables=line, temperature=150, pressure=3
		),
	}
	inactive = _ensure_program(
		"program_inactive", steam, minutes=30, water=20, consumables=line, temperature=134, pressure=3
	)
	if frappe.db.get_value("Process Program", inactive, "is_active"):
		frappe.db.set_value("Process Program", inactive, "is_active", 0)
	programs["program_inactive"] = inactive

	result = {
		"steam": steam,
		"steam_copy_target": target,
		"washer": washer,
		"retired": retired,
		**programs,
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo in nhãn QR đối tượng (FEAT-005) ---------------------------------------------------------------
CODES_STATION = "TR-001"
CODES_PRINTER_NAME = "DEMO-CODES network printer"
CODES_PRINTER_HOST = "127.0.0.1"
CODES_PRINTER_PORT = 19101
CODES_PORT_ENV = "TC_E2E_CODES_PRINTER_PORT"


def _codes_port(port):
	value = port if port not in (None, "") else os.environ.get(CODES_PORT_ENV) or CODES_PRINTER_PORT
	text = str(value).strip()
	if not text.isdigit() or not 1 <= int(text) <= 65535:
		frappe.throw(_("Demo printer port must be a number from 1 to 65535."))
	return int(text)


def _ensure_codes_printer(port):
	"""Máy in mạng demo tại TR-001 (host 127.0.0.1, cổng `port`): đường server gửi ZPL tới socket giả của e2e."""
	name = frappe.db.get_value(
		"Printer", {"station": CODES_STATION, "printer_name": CODES_PRINTER_NAME}, "name"
	)
	if not name:
		name = factories.make_printer(
			CODES_STATION, STEAM_LABEL, host=CODES_PRINTER_HOST, name=CODES_PRINTER_NAME
		)
	frappe.db.set_value(
		"Printer",
		name,
		{"is_active": 1, "host": CODES_PRINTER_HOST, "port": port, "supports_unicode": 0},
	)
	return name


def ensure_codes_demo(port=None):
	"""Dữ liệu demo cho e2e Desk in nhãn QR đối tượng (SCR-33, FEAT-005) trên site dev/test; idempotent, trả và in JSON.

	- ``printer``: máy in mạng ``DEMO-CODES network printer`` tại TR-001, host ``127.0.0.1``, cổng `port` (mặc định
	  biến môi trường ``TC_E2E_CODES_PRINTER_PORT``, rồi 19101), không hỗ trợ Unicode; e2e dựng socket TCP giả ở cổng
	  này để nhận ZPL do worker gửi. Gọi lại thì bật lại máy in và cập nhật cổng.
	- ``equipment`` / ``equipment_2``: máy hấp demo đang Sẵn sàng của ``ensure_equipment_demo`` (mã TB- Active);
	  ``retired``: máy demo đã ngừng sử dụng (không in được nhãn).
	- ``label_item``: Item nhãn hấp ``VT-NHAN-HAP`` để cấp mã cuộn ``CN-``; mẫu nhãn đối tượng mẫu.
	"""
	_require_dev_site()
	port = _codes_port(port)
	ensure_sample_templates()
	ensure_object_templates()
	factories.make_label_items()
	equipment = ensure_equipment_demo()
	result = {
		"equipment": equipment["steam"],
		"equipment_2": equipment["steam_copy_target"],
		"retired": equipment["retired"],
		"printer": _ensure_codes_printer(port),
		"printer_port": port,
		"label_item": STEAM_LABEL,
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo danh mục dụng cụ Desk SCR-01 (FEAT-014) -------------------------------------------------------
# Instrument không xóa được và Ngừng sử dụng / mã GIAI là một chiều: bản ghi cố định được dùng lại; dụng cụ để
# ngừng sử dụng và dụng cụ để cấp mã GIAI được thay bằng dụng cụ mới (số thứ tự kế tiếp) khi đã bị e2e dùng.
INSTR_GROUP = "DEMO-E2E-GROUP"
INSTR_GROUP_INTERVAL = 40
INSTR_GROUP_TYPE = "Blade Check"
INSTR_FULL = "DEMO-E2E-FULL"
INSTR_NO_MAX = "DEMO-E2E-NOMAX"
INSTR_RETIRE_PREFIX = "DEMO-E2E-RET-"
INSTR_GIAI_PREFIX = "DEMO-E2E-GIAI-"
INSTR_FULL_MAX_CYCLES = 500
INSTR_FULL_VALUE = 1_500_000
# loại bộ riêng cho e2e SCR-01 (không đổi BOM của bộ demo T4 mà tests_e2e/test_station_t4.py dùng)
INSTR_SET_TYPES = {"set_type_steam": "DEMOI4S", "set_type_plasma": "DEMOI4P", "set_type_retire": "DEMOI4R"}


def _instrument_catalog():
	"""Tên hiển thị demo (bản dịch tiếng Việt trong vi.csv)."""
	t4 = _t4_catalog()
	return {
		"full": _("Demo e2e Metzenbaum scissors", lang="vi"),
		"no_max": _("Demo e2e needle holder without max cycles", lang="vi"),
		"retire": _("Demo e2e forceps to retire", lang="vi"),
		"giai": _("Demo e2e retractor for laser GIAI", lang="vi"),
		"set_type_steam": ("Steam", _("Demo e2e steam set", lang="vi"), t4["Steam"]["pack_type"]),
		"set_type_plasma": ("Plasma", _("Demo e2e plasma set", lang="vi"), t4["Plasma"]["pack_type"]),
		"set_type_retire": (
			"Steam",
			_("Demo e2e set with instrument to retire", lang="vi"),
			t4["Steam"]["pack_type"],
		),
	}


def _ensure_full_instrument(name):
	if not frappe.db.exists("Instrument", INSTR_FULL):
		factories.make_instrument(
			INSTR_FULL,
			name,
			spaulding=T4_INSTRUMENT_SPAULDING,
			methods=("Steam 134", "Plasma"),
			max_cycles=INSTR_FULL_MAX_CYCLES,
			group=INSTR_GROUP,
			manufacturer="E2E Maker",
			model="E2E-MZB-1",
			value=INSTR_FULL_VALUE,
		)
	_ensure_instrument_photo(INSTR_FULL)
	return INSTR_FULL


def _next_candidate(prefix, name, usable):
	"""Dụng cụ `<prefix>NN` đầu tiên còn `usable`; không còn thì tạo dụng cụ số kế tiếp. Trả mã."""
	codes = sorted(frappe.get_all("Instrument", filters={"name": ["like", f"{prefix}%"]}, pluck="name"))
	for code in codes:
		if usable(code):
			return code
	code = f"{prefix}{len(codes) + 1:02d}"
	while frappe.db.exists("Instrument", code):
		code = f"{prefix}{int(code[len(prefix) :]) + 1:02d}"
	factories.make_instrument(code, name, spaulding=T4_INSTRUMENT_SPAULDING, methods=("Steam 134",))
	return code


def _giai_candidate(code):
	row = frappe.db.get_value("Instrument", code, ["status", "giai_code"], as_dict=True)
	return row.status == "Active" and not row.giai_code


def _ensure_bom_line(set_type, instrument):
	"""Thêm `instrument` vào BOM của `set_type` (dòng cuối) nếu phiên bản hiệu lực và phiên bản mới nhất chưa có: phiên
	bản BOM mới chép từ phiên bản mới nhất, hiệu lực hôm nay, hoặc cùng ngày với phiên bản đã lên lịch mới nhất (ngày
	hiệu lực không được sớm hơn phiên bản mới nhất; phiên bản đã lưu không sửa được, FEAT-015)."""
	history = bom_versions.versions(set_type)
	latest = history[0]["bom_version"] if history else 0
	for version in {bom_versions.effective_version(set_type) or 0, latest}:
		if frappe.db.exists(
			"Set BOM Item", {"set_type": set_type, "bom_version": version, "instrument": instrument}
		):
			return
	day = max(
		bom_versions.today(), (history[0]["effective_from"] if history else None) or bom_versions.today()
	)
	retired = set(frappe.get_all("Instrument", filters={"status": "Retired"}, pluck="name"))
	# dụng cụ demo đã bị e2e ngừng sử dụng không chép sang phiên bản mới (FR-M1-03.6)
	lines = [
		{"instrument": row["instrument"], "qty": row["qty"]}
		for row in (bom.lines(set_type, latest) if latest else [])
		if row["instrument"] not in retired
	]
	lines.append({"instrument": instrument, "qty": 1})
	bom_versions.create_version(set_type, lines, day, _("Demo data"), latest)


def ensure_instrument_demo():
	"""Dữ liệu demo cho e2e Desk danh mục dụng cụ (SCR-01, FEAT-014) trên site dev/test; idempotent, trả và in JSON.

	- ``group``: nhóm ``DEMO-E2E-GROUP`` có ngưỡng 40 chu trình, Kiểm tra lưỡi.
	- ``full``: dụng cụ đủ dữ liệu (Spaulding, Hấp 134 °C + Plasma, hãng, model, cơ số, giá trị, nhóm, ảnh riêng tư có
	  thumbnail), nằm trong BOM hiện hành của hai loại bộ demo ``set_type_steam`` (hấp) và ``set_type_plasma``
	  (plasma); ``set_steam``/``set_plasma``: một bộ của mỗi loại đã qua T1-T3, mở được ở T4 (TR-004).
	- ``no_max``: dụng cụ thiếu cơ số (Chưa xác định).
	- ``retire``: dụng cụ Đang dùng nằm trong BOM hiện hành của ``set_type_retire``; ``giai``: dụng cụ chưa có mã GIAI.
	  Hai dụng cụ này bị e2e dùng hết (ngừng sử dụng, cấp mã là một chiều) nên lần gọi sau tạo dụng cụ mới.
	File PDF quá cỡ cho e2e IFU do test tự tạo tạm (không lưu ở đây).
	"""
	_require_dev_site()
	names = _instrument_catalog()
	factories.make_instrument_group(
		INSTR_GROUP,
		interval=INSTR_GROUP_INTERVAL,
		maint_type=INSTR_GROUP_TYPE,
		description=_("Demo e2e group with a maintenance threshold", lang="vi"),
	)
	full = _ensure_full_instrument(names["full"])
	if not frappe.db.exists("Instrument", INSTR_NO_MAX):
		factories.make_instrument(
			INSTR_NO_MAX, names["no_max"], spaulding=T4_INSTRUMENT_SPAULDING, methods=("Steam 134",)
		)
	retire = _next_candidate(
		INSTR_RETIRE_PREFIX,
		names["retire"],
		lambda code: frappe.db.get_value("Instrument", code, "status") == "Active",
	)
	giai = _next_candidate(
		INSTR_GIAI_PREFIX,
		names["giai"],
		lambda code: _giai_candidate(code),
	)

	set_types = {}
	for key, code in INSTR_SET_TYPES.items():
		method, set_name, pack_type = names[key]
		line = retire if key == "set_type_retire" else full
		spec = {"set_name": set_name, "pack_type": pack_type, "bom": ((line, set_name, 1),)}
		set_types[key] = _ensure_set_type(method, spec, code=code, ensure_instruments=False)
		_ensure_bom_line(code, line)

	result = {
		"group": INSTR_GROUP,
		"full": full,
		"no_max": INSTR_NO_MAX,
		"retire": retire,
		"giai": giai,
		**set_types,
		"set_steam": _ensure_set(set_types["set_type_steam"], T4_GATES_READY),
		"set_plasma": _ensure_set(set_types["set_type_plasma"], T4_GATES_READY),
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo vật tư tiêu hao và nhập kho Desk SCR-24 (FEAT-041) --------------------------------------------
# Stock Entry và Item không xóa được: vật tư mẫu có mã cố định (dùng lại); mã lô và số chứng từ do e2e tự sinh duy nhất.
INV_SUPPLIER = "TraceCore NCC"
INV_MIN_QTY = 10
# khóa -> (mã Item, nhóm vật tư CSSD, lớp chỉ thị hóa học)
INV_ITEMS = {
	"ci": ("TCINV-CI5", "Chemical Indicator", "5"),
	"bi": ("TCINV-BI", "Biological Indicator", None),
	"pk": ("TCINV-PK", "Packaging", None),
	"ch": ("TCINV-CH", "Chemical", None),
}


def _inventory_warehouse(company):
	"""Kho lá của Company, ưu tiên ``Stores - <abbr>``; site đã chạy Setup Wizard đặt tên kho theo ngôn ngữ nên tra theo Company."""
	abbr = frappe.db.get_value("Company", company, "abbr")
	if frappe.db.exists("Warehouse", f"Stores - {abbr}"):
		return f"Stores - {abbr}"
	warehouse = frappe.db.get_value(
		"Warehouse",
		{"company": company, "is_group": 0, "disabled": 0},
		"name",
		order_by="creation asc",
	)
	if not warehouse:
		frappe.throw(_("Company {0} has no warehouse.").format(company))
	return warehouse


def _ensure_inventory_item(code, group, ci_class, warehouse):
	item = factories.make_item(code, group, ci_class=ci_class, apply_rules=True)
	if not item.get("reorder_levels"):
		item.append(
			"reorder_levels",
			{
				"warehouse": warehouse,
				"warehouse_reorder_level": INV_MIN_QTY,
				"warehouse_reorder_qty": INV_MIN_QTY,
				"material_request_type": "Purchase",
			},
		)
		item.save(ignore_permissions=True)
	return item.name


def ensure_inventory_demo():
	"""Dữ liệu demo cho e2e Desk nhập kho vật tư (SCR-24, FEAT-041) trên site dev/test; idempotent, trả và in JSON.

	Company thử (chỉ tạo nếu site chưa có), kho lá của Company, nhà cung cấp và bốn vật tư có tồn tối thiểu theo kho:
	``ci`` (chỉ thị hóa học lớp 5), ``bi`` (chỉ thị sinh học), ``ch`` (hóa chất) bắt buộc hạn dùng; ``pk`` (bao gói)
	không bắt buộc hạn. Tài khoản TC R09 do ``scripts/e2e_prepare.sh`` tạo (mật khẩu ngẫu nhiên, không nằm ở đây).
	"""
	_require_dev_site()
	masters = factories.ensure_stock_masters()
	company = frappe.db.get_single_value("Global Defaults", "default_company") or masters["company"]
	warehouse = _inventory_warehouse(company)
	items = {
		key: _ensure_inventory_item(code, group, ci_class, warehouse)
		for key, (code, group, ci_class) in INV_ITEMS.items()
	}
	result = {
		"company": company,
		"warehouse": warehouse,
		"supplier": factories.make_supplier(INV_SUPPLIER),
		**items,
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo loại bộ và BOM theo phiên bản (FEAT-015) ----------------------------------------------------------------
# Loại bộ / dòng BOM / dụng cụ không xóa được: dữ liệu cố định, dùng lại giữa các lần chạy e2e.
SETTYPE_CODES = {"set_type": "DEMOF15S", "set_type_inflight": "DEMOF15T", "set_type_edit": "DEMOF15E"}
SETTYPE_TRAY_FIELDS = ("tray_image", "tray_image_2", "tray_image_3")


def _set_type_catalog():
	"""Mã và tên hiển thị demo FEAT-015 (bản dịch tiếng Việt trong vi.csv)."""
	return {
		"packs": {
			"pack_short": ("DEMO-F15-GOI-30", _("Demo e2e crepe paper 30 days", lang="vi"), 30),
			"pack_long": ("DEMO-F15-GOI-180", _("Demo e2e pouch 180 days", lang="vi"), 180),
			"pack_none": ("DEMO-F15-GOI-0", _("Demo e2e wrap without shelf life", lang="vi"), 0),
			"pack_r10": ("DEMO-F15-GOI-R10", _("Demo e2e container for R10 shelf life", lang="vi"), 90),
		},
		"instruments": {
			"steam_1": ("DEMO-F15-KEO", _("Demo e2e dissecting scissors", lang="vi"), "Steam"),
			"steam_2": ("DEMO-F15-KEP", _("Demo e2e Kocher forceps", lang="vi"), "Steam"),
			"steam_3": ("DEMO-F15-BAT", _("Demo e2e stainless bowl", lang="vi"), "Steam"),
			"plasma": ("DEMO-F15-PLASMA", _("Demo e2e plasma-only scope", lang="vi"), "Plasma"),
			"retired": ("DEMO-F15-RETIRED", _("Demo e2e retired forceps", lang="vi"), "Steam"),
		},
		"set_types": {
			"set_type": _("Demo e2e versioned steam set", lang="vi"),
			"set_type_inflight": _("Demo e2e set with a set in its cycle", lang="vi"),
			"set_type_edit": _("Demo e2e set for BOM editing", lang="vi"),
		},
	}


def _ensure_retired(code):
	from tracecore.instrument import catalog

	if frappe.db.get_value("Instrument", code, "status") != "Retired":
		catalog.retire(code, _("Demo data", lang="vi"), confirm=True)


def _ensure_demo_set_type(code, name, method, pack_type, lines):
	"""Loại bộ demo (khoa demo, GTIN test, loại gói) cùng BOM v1 `lines` [(mã, số lượng)] nếu chưa có; trả mã."""
	if not frappe.db.exists("Instrument Set Type", code):
		bom_versions.create_set_type(
			{
				"type_code": code,
				"set_type_name": name,
				"method": method,
				"gtin": _free_demo_gtin(),
				"department": _demo_department(),
				"default_pack_type": pack_type,
			},
			[{"instrument": instrument, "qty": qty} for instrument, qty in lines],
		)
	return code


def _ensure_tray_photos(code):
	"""Ba ảnh bộ đã xếp riêng tư (qua kiểm file và thumbnail của ``media``, S6) cho các ô ảnh còn trống."""
	doc = frappe.get_doc("Instrument Set Type", code)
	missing = [field for field in SETTYPE_TRAY_FIELDS if not doc.get(field)]
	if not missing:
		return
	for field in missing:
		position = SETTYPE_TRAY_FIELDS.index(field) + 1
		photo = factories.attach_set_type_photo(
			code, field, _demo_png(f"{code}-{position}"), f"{code.lower()}-tray-{position}.png"
		)
		doc.set(field, photo.file_url)
	doc.save(ignore_permissions=True)


def _latest_lines(set_type):
	history = bom_versions.versions(set_type)
	latest = history[0] if history else None
	lines = (
		[(row["instrument"], row["qty"]) for row in bom.lines(set_type, latest["bom_version"])]
		if latest
		else []
	)
	return latest, lines


def _demo_version(set_type, day, reason, change):
	"""Phiên bản mới từ phiên bản mới nhất với thay đổi `change(lines) -> lines`, hiệu lực `day`; trả số phiên bản."""
	latest, lines = _latest_lines(set_type)
	return bom_versions.create_version(
		set_type,
		[{"instrument": instrument, "qty": qty} for instrument, qty in change(lines)],
		day,
		reason,
		latest["bom_version"] if latest else 0,
	)["bom_version"]


def _bump_first_qty(lines):
	"""Đổi số lượng dòng đầu (1 → 2 → 3 → 1 …), giữ các dòng khác."""
	(instrument, qty), rest = lines[0], lines[1:]
	return [(instrument, qty % 3 + 1), *rest]


def _toggle_line(code):
	"""Thêm `code` (1 cái) nếu chưa có, bỏ nếu đã có."""

	def change(lines):
		if any(instrument == code for instrument, _qty in lines):
			return [(instrument, qty) for instrument, qty in lines if instrument != code]
		return [*lines, (code, 1)]

	return change


def _ensure_scheduled_version(set_type):
	"""Phiên bản đã lên lịch (ngày mai, hoặc cùng ngày phiên bản mới nhất nếu muộn hơn) nếu chưa có; trả số phiên bản."""
	live = bom_versions.live_map([set_type])[set_type]
	if live["scheduled"]:
		return live["scheduled"][-1]
	latest, _lines = _latest_lines(set_type)
	day = max(getdate(add_days(today(), 1)), latest["effective_from"] or getdate(today()))
	return _demo_version(set_type, day, _("Demo scheduled BOM change", lang="vi"), _bump_first_qty)


def _inflight_set(set_type, toggled):
	"""Bộ đã qua T1-T3, chưa có Cycle ID, ghim phiên bản cũ hơn phiên bản hiệu lực (FR-M1-04.1); trả (Set ID, ghim).

	Không còn (bộ cũ đã được đóng gói) → bộ mới mở chu trình (ghim phiên bản hiệu lực N) rồi lưu phiên bản N+1 hiệu lực
	hôm nay (thêm/bỏ dụng cụ `toggled`), như R02 sửa BOM khi bộ đang giữa chu trình.
	"""
	effective = bom_versions.effective_version(set_type) or 0
	for row in frappe.get_all(
		"Set Unit",
		filters={"set_type": set_type},
		fields=["name", "status", "active_cycle_id", "current_cycle_no", "cycle_bom_version"],
		order_by="creation asc",
	):
		if _matches(_gate_results(row), T4_GATES_READY) and 0 < row.cycle_bom_version < effective:
			return row.name, row.cycle_bom_version
	unit = frappe.get_doc({"doctype": "Set Unit", "set_type": set_type, "max_cycles": 300}).insert(
		ignore_permissions=True
	)
	factories.make_cycle(unit.name, passed=T4_GATES_READY)
	_demo_version(
		set_type, getdate(today()), _("Demo BOM change during a cycle", lang="vi"), _toggle_line(toggled)
	)
	return unit.name, frappe.db.get_value("Set Unit", unit.name, "cycle_bom_version")


def ensure_set_type_demo():
	"""Dữ liệu demo cho e2e Desk loại bộ và BOM theo phiên bản (SCR-02, FEAT-015) trên site dev/test; idempotent, trả
	và in JSON.

	- ``pack_short``/``pack_long``: loại gói có hạn lưu 30/180 ngày; ``pack_none``: loại gói hạn 0 (không được gợi ý,
	  BRU-REP-009); ``pack_r10``: loại gói riêng để R10 sửa hạn lưu (e2e đổi giá trị mỗi lần chạy).
	- ``steam_1..3``: dụng cụ hấp có ảnh; ``plasma``: dụng cụ chỉ Plasma (lỗi tương thích ở loại bộ hấp, FR-M1-03.3);
	  ``retired``: dụng cụ đã Ngừng sử dụng (FR-M1-03.6).
	- ``set_type`` (hấp, loại gói ``pack_short``): phiên bản ``effective_version`` đang hiệu lực, phiên bản
	  ``scheduled_version`` lên lịch ngày mai (ngày sau chạy lại thì lên lịch phiên bản mới), ba ảnh bộ đã xếp.
	- ``set_type_inflight``: bộ ``set_inflight`` đã qua T1-T3 ghim ``inflight_version`` < ``inflight_effective`` (mở ở
	  T4 TR-004 phải hiện BOM đã ghim). Chỉ đọc ở e2e; đã bị đóng gói thì lần gọi sau tạo bộ mới và phiên bản mới.
	- ``set_type_edit`` (loại gói ``pack_long``, không ghi đè hạn lưu): e2e sửa BOM thêm phiên bản hiệu lực hôm nay.
	"""
	_require_dev_site()
	catalog = _set_type_catalog()
	packs = {key: _ensure_pack_type(spec) for key, spec in catalog["packs"].items()}
	instruments = {}
	for key, (code, name, method) in catalog["instruments"].items():
		_ensure_instrument(code, name, method)
		instruments[key] = code
	_ensure_retired(instruments["retired"])
	names = catalog["set_types"]
	steam = [instruments[key] for key in ("steam_1", "steam_2", "steam_3")]

	set_type = _ensure_demo_set_type(
		SETTYPE_CODES["set_type"],
		names["set_type"],
		"Steam",
		packs["pack_short"],
		[(steam[0], 2), (steam[1], 1)],
	)
	_ensure_tray_photos(set_type)
	scheduled = _ensure_scheduled_version(set_type)

	inflight_type = _ensure_demo_set_type(
		SETTYPE_CODES["set_type_inflight"],
		names["set_type_inflight"],
		"Steam",
		packs["pack_short"],
		[(steam[0], 1), (steam[1], 1)],
	)
	set_inflight, inflight_version = _inflight_set(inflight_type, steam[2])

	edit_type = _ensure_demo_set_type(
		SETTYPE_CODES["set_type_edit"],
		names["set_type_edit"],
		"Steam",
		packs["pack_long"],
		[(steam[0], 1), (steam[1], 2)],
	)

	result = {
		**packs,
		**instruments,
		"set_type": set_type,
		"effective_version": bom_versions.effective_version(set_type),
		"scheduled_version": scheduled,
		"set_type_inflight": inflight_type,
		"set_inflight": set_inflight,
		"inflight_version": inflight_version,
		"inflight_effective": bom_versions.effective_version(inflight_type),
		"set_type_edit": edit_type,
		"department": _demo_department(),
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo T6 kho vô khuẩn (FEAT-025) ------------------------------------------------------------------
T6_STATION = "TR-006"
T6_SET_TYPE = "DEMOT6S"
T6_LOCATIONS = {"location": "DEMO-T6 Shelf A", "location_2": "DEMO-T6 Shelf B"}
T6_STORE_DAYS = 30  # hạn của gói demo "còn xa" (ngoài danh sách sắp hết hạn 7 ngày)
T6_EXPIRING_DAYS = 3  # hạn của gói demo nằm trong danh sách sắp hết hạn 7 ngày (FR-M2-13.2)


def ensure_t6_e2e_user(station, password):
	"""User kiosk trạm T6 (khu vô khuẩn → TC R06) cho e2e màn kho vô khuẩn (FEAT-025), đăng ký OTP App.

	Tách khỏi `ensure_e2e_users` để không đổi khóa trả về của hàm đó; bí mật chỉ ghi vào file env riêng tư của e2e.
	"""
	from tracecore.setup import provision

	_require_dev_site()
	_require_administrator()
	with _temporary_r10():
		user = provision.station_user(station, password)
		return {"t6_user": user, "t6_otp_secret": _enroll_otp(user)}


def _t6_location(location_name):
	"""Kệ demo `KE-####` đang dùng của TR-006 (tạo một lần theo tên kệ); trả mã kệ."""
	code = frappe.db.get_value(
		"Sterile Location", {"location_name": location_name, "zone_station": T6_STATION}, "name"
	)
	if not code:
		code = factories.make_sterile_location(location_name, T6_STATION).name
	if not frappe.db.get_value("Sterile Location", code, "is_active"):
		frappe.db.set_value("Sterile Location", code, "is_active", 1)
	return code


def _t6_candidate(status, expiring=False, location=None):
	"""Gói demo đầu tiên (loại bộ `T6_SET_TYPE`) ở `status`, hạn trong (expiring) hoặc ngoài 7 ngày tới."""
	from tracecore.reprocessing import storage

	horizon = add_days(today(), storage.EXPIRING_DAYS)
	filters = {
		"docstatus": 1,
		"set_type": T6_SET_TYPE,
		"status": status,
		"expiry": ["between", [today(), horizon]] if expiring else [">", horizon],
		"location": location or ["is", "not set"],
	}
	return frappe.db.get_value("Pack", filters, "name", order_by="creation asc")


def _t6_new_pack(status="Released", expiry_days=T6_STORE_DAYS, location=None, passed=factories.ALL_GATES):
	"""Gói mới của loại bộ demo T6 qua `factories.make_released_pack`; có `location` thì nhập kho thật lên kệ đó."""
	from tracecore.reprocessing import storage

	pack = factories.make_released_pack(
		status=status, expiry_days=expiry_days, passed=passed, set_type=T6_SET_TYPE
	)
	if location:
		storage.putaway(pack.name, location, T6_STATION)
	return pack.name


def ensure_t6_demo():
	"""Chuẩn bị màn T6 kho vô khuẩn (SCR-11) tại TR-006 trên site dev/test; idempotent, trả và in JSON các mã để quét.

	- ``location``, ``location_2``: hai kệ ``KE-`` đang dùng của TR-006.
	- ``pack_released``: gói Released (bộ đủ 5 cổng Đạt), chưa lên kệ, hạn 30 ngày — để nhập kho.
	- ``pack_not_released``: gói Packed (bộ mới qua T1-T4) — nhập kho bị chặn ``PACK_NOT_RELEASED``.
	- ``pack_stored``: gói đang trong kho trên ``location``, hạn 30 ngày — để báo rách.
	- ``pack_expiring``: gói đang trong kho trên ``location_2``, hạn 3 ngày — hiện ở danh sách sắp hết hạn 7 ngày.
	Gói đã bị nhập kho/báo rách/hết hạn được thay bằng gói mới khi gọi lại.
	"""
	_require_dev_site()
	_ensure_set_type("Steam", _t4_catalog()["Steam"], code=T6_SET_TYPE)
	locations = {key: _t6_location(name) for key, name in T6_LOCATIONS.items()}
	result = {
		**locations,
		"pack_released": _t6_candidate("Released") or _t6_new_pack(),
		"pack_not_released": _t6_candidate("Packed")
		or _t6_new_pack(status="Packed", passed=("T1", "T2", "T3", "T4")),
		"pack_stored": _t6_candidate("In Sterile Stock", location=locations["location"])
		or _t6_new_pack(location=locations["location"]),
		"pack_expiring": _t6_candidate("In Sterile Stock", expiring=True, location=locations["location_2"])
		or _t6_new_pack(expiry_days=T6_EXPIRING_DAYS, location=locations["location_2"]),
	}
	print(json.dumps(result, sort_keys=True))
	return result
