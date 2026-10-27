"""Dữ liệu demo cho site dev/test (developer_mode hoặc allow_tests; không chạy trên production).

- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_demo_set`` in Set ID GIAI thử để quét ở /app/station
  (loại bộ DEMO có BOM một dụng cụ demo; Set Unit cấp qua ``set_units.issue_batch``).
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
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_t2_demo`` chuẩn bị màn T2 lô rửa (SCR-06, FEAT-021) tại
  TR-002: máy rửa, chương trình, lô hóa chất, bộ đã qua T1, bộ chờ rửa lại, một lô đang chạy; in JSON các mã.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_t5_demo`` chuẩn bị màn T5 nạp mẻ (SCR-09, FEAT-022) tại
  TR-005 (máy hấp/plasma, chương trình, gói đã qua T4, mẻ đang chạy); in JSON các mã để quét.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_t1_demo`` chuẩn bị màn T1 tiếp nhận (SCR-05, FEAT-019) tại
  TR-001: thẻ người giao thuộc khoa demo, bộ Chờ tiếp nhận / Mới tạo để tiếp nhận, bộ Vô khuẩn (bị từ chối), một Set ID
  hợp lệ về định dạng nhưng chưa cấp; in JSON các mã.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_t6_demo`` chuẩn bị màn T6 kho vô khuẩn (SCR-11) tại
  TR-006: hai kệ ``KE-``, gói đã giải phóng, gói chưa giải phóng, gói trong kho, gói sắp hết hạn; in JSON các mã.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_t3_demo`` chuẩn bị màn T3 kiểm đếm lắp ráp (SCR-07) tại
  TR-003: bộ đã qua T1-T2 để đếm đủ / đếm thiếu / rẽ nhánh, bộ chưa qua lô rửa; in JSON các mã.
"""

import io
import json
import os
import secrets
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, now_datetime, today

from tracecore.core import client_time, code_registry, gs1, step_gate
from tracecore.core import print as core_print
from tracecore.equipment import status as equipment_status
from tracecore.instrument import bom, bom_versions, set_units
from tracecore.reprocessing import sterilizing, washing
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


def ensure_t2_e2e_user(station, password):
	"""User kiosk trạm T2 (khu bẩn → TC R03) cho e2e màn lô rửa (FEAT-021), đăng ký OTP App như `ensure_e2e_users`.

	Tách khỏi `ensure_e2e_users` để không đổi khóa trả về của hàm đó; bí mật chỉ ghi vào file env riêng tư của e2e.
	"""
	from tracecore.setup import provision

	_require_dev_site()
	_require_administrator()
	with _temporary_r10():
		user = provision.station_user(station, password)
		return {"t2_user": user, "t2_otp_secret": _enroll_otp(user)}


def ensure_t5_e2e_user(station, password):
	"""User kiosk trạm T5 (khu sạch → TC R04, thêm TC R05 của KTV tiệt khuẩn) cho e2e màn nạp mẻ (FEAT-022), OTP App.

	Khu sạch cấp role R04 (T3/T4/T5 chung khu) nhưng RPC nạp mẻ chỉ nhận R05, R02, System Manager (A-16 Q13) nên user
	e2e được thêm R05. Tách khỏi `ensure_e2e_users`; bí mật chỉ ghi vào file env riêng tư của e2e.
	"""
	from tracecore.setup import provision

	_require_dev_site()
	_require_administrator()
	with _temporary_r10():
		user = provision.station_user(station, password)
		frappe.get_doc("User", user).add_roles("TC R05")
		return {"t5_user": user, "t5_otp_secret": _enroll_otp(user)}


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
	"""Tạo (nếu chưa có) loại bộ DEMO (BOM một dụng cụ demo hấp) và một Set Unit cấp qua Cấp Set ID; trả và in Set ID."""
	_require_dev_site()
	steam = _t4_catalog()["Steam"]
	instrument, instrument_name, _qty = steam["bom"][0]
	_ensure_instrument(instrument, instrument_name, "Steam")
	lines = [{"instrument": instrument, "qty": 1}]
	if not frappe.db.exists("Instrument Set Type", DEMO_SET_TYPE):
		bom_versions.create_set_type(
			{
				"type_code": DEMO_SET_TYPE,
				"set_type_name": "Demo set",
				"method": "Steam",
				"department": _demo_department(),
				"default_pack_type": _ensure_pack_type(steam["pack_type"]),
			},
			lines,
		)
	elif not bom_versions.effective_version(DEMO_SET_TYPE):
		# loại bộ DEMO tạo trước FEAT-016 không có BOM: cấp Set ID cần BOM hiệu lực (G5)
		latest = bom_versions.versions(DEMO_SET_TYPE)
		bom_versions.create_version(
			DEMO_SET_TYPE,
			lines,
			bom_versions.today(),
			_("Demo data"),
			latest[0]["bom_version"] if latest else 0,
		)
	set_id = frappe.db.get_value(
		"Set Unit", {"set_type": DEMO_SET_TYPE}, "name", order_by="creation asc, name asc"
	)
	if not set_id:
		set_id = _issue_one(DEMO_SET_TYPE)
	print(set_id)
	return set_id


def _issue_one(set_type):
	"""Một Set Unit Mới tạo của `set_type` qua Cấp Set ID (FEAT-016: Set Unit chỉ tạo qua ``set_units.issue_batch``)."""
	return set_units.issue_batch(set_type, 1, max_cycles=300)[0]


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
	if not frappe.db.get_value("Instrument Set Type", code, "department"):
		# loại bộ demo tạo trước FEAT-015 chưa có khoa; cấp Set ID bắt buộc khoa (A-13 G5)
		frappe.db.set_value(
			"Instrument Set Type", code, "department", _demo_department(), update_modified=False
		)
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


def _ensure_set(set_type, passed, reminder=False, exclude=()):
	"""Set Unit đầu tiên của `set_type` (ngoài `exclude`) có đúng các cổng `passed` Đạt (còn lại Chưa) và chưa có
	Cycle ID.

	`reminder` chọn bộ có (True, kèm nhắc tra dầu đến hạn) hoặc không có (False) bản ghi bảo dưỡng tra dầu.

	Không có (vd bộ cũ đã được đóng gói) thì tạo bộ mới và mở chu trình. Trả Set ID.
	"""
	rows = frappe.get_all(
		"Set Unit",
		filters={"set_type": set_type},
		fields=["name", "status", "active_cycle_id", "current_cycle_no"],
		order_by="name asc",  # Set ID cấp theo series tăng dần, cùng độ rộng: thứ tự ổn định giữa các lần gọi
	)
	for row in rows:
		if row.name in exclude:
			continue
		if _matches(_gate_results(row), passed) and _has_lube_reminder(row.name) == reminder:
			return row.name
	set_id = _issue_one(set_type)
	factories.make_cycle(set_id, passed=passed)
	if reminder:
		_ensure_lube_reminder(set_id)
	return set_id


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
		order_by="creation asc, name asc",
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

	steam = _ensure_set(set_types["Steam"], T4_GATES_READY)
	# FEAT-009: hai bộ hấp riêng cho e2e đóng gói offline (tests_e2e/test_station_offline.py), không đụng bộ của T4
	offline_1 = _ensure_set(set_types["Steam"], T4_GATES_READY, exclude=(steam,))
	offline_2 = _ensure_set(set_types["Steam"], T4_GATES_READY, exclude=(steam, offline_1))
	result = {
		"set_steam": steam,
		"set_offline_1": offline_1,
		"set_offline_2": offline_2,
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
		order_by="creation asc, name asc",
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
		order_by="creation asc, name asc",
	):
		if _matches(_gate_results(row), T4_GATES_READY) and 0 < row.cycle_bom_version < effective:
			return row.name, row.cycle_bom_version
	set_id = _issue_one(set_type)
	factories.make_cycle(set_id, passed=T4_GATES_READY)
	_demo_version(
		set_type, getdate(today()), _("Demo BOM change during a cycle", lang="vi"), _toggle_line(toggled)
	)
	return set_id, frappe.db.get_value("Set Unit", set_id, "cycle_bom_version")


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


# --- Demo T2 lô rửa (FEAT-021, SCR-06) ------------------------------------------------------------------
T2_STATION = "TR-002"
T2_CHEMICAL = "DEMO-T2-ENZ"
T2_LOT_OK = "DEMO-T2-ENZ-OK"
T2_LOT_EXPIRED = "DEMO-T2-ENZ-HET"
T2_SERIALS = {
	"machine": "DEMO-T2-WASH-01",
	"machine_two_door": "DEMO-T2-WASH-02",
	"machine_locked": "DEMO-T2-WASH-LOCK",
	"machine_connected": "DEMO-T2-WASH-API",
}
T2_PARAMETERS = [
	{
		"parameter_name": "Disinfection temperature",
		"unit": "°C",
		"min_value": 90,
		"max_value": 95,
		"required": 1,
	},
	{"parameter_name": "Hold time", "unit": "min", "min_value": 5, "max_value": 0, "required": 1},
	{"parameter_name": "Chemical dose", "unit": "ml", "min_value": 0, "max_value": 0, "required": 0},
]
T2_READY_SETS = 3


def _t2_machine(key, **fields):
	"""Máy rửa demo theo serial cố định (Equipment không xóa được nên dùng lại); trả TB-####."""
	name = frappe.db.get_value("Equipment", {"serial_no": T2_SERIALS[key]}, "name")
	if name:
		return name
	values = {
		"name": f"Demo washer {key}",
		"equipment_type": "Washer-Disinfector",
		"serial": T2_SERIALS[key],
		"zone_in": "ZONE-DIRTY",
		"zone_out": None,
		"manufacturer": EQ_MANUFACTURER,
		"model": "DEMO-W2",
		**fields,
	}
	return factories.make_equipment(**values).name


def _t2_program(equipment):
	"""Chương trình rửa đang dùng đầu tiên của máy (tạo nếu chưa có), có hóa chất và tham số."""
	name = frappe.db.get_value(
		"Process Program", {"equipment": equipment, "is_active": 1}, "name", order_by="creation asc, name asc"
	)
	if name:
		return name
	code = "DEMO-T2-" + equipment.replace("TB-", "")
	return factories.make_wash_program(
		equipment, chemical=T2_CHEMICAL, code=code, parameters=T2_PARAMETERS
	).name


def _t2_chemical_lots():
	factories.make_item(T2_CHEMICAL, "Chemical", has_batch_no=1, apply_rules=True)
	if not frappe.db.exists("Batch", T2_LOT_OK):
		factories.make_chemical_batch(T2_CHEMICAL, batch_id=T2_LOT_OK, expiry_days=365, qty=100)
	if not frappe.db.exists("Batch", T2_LOT_EXPIRED):
		factories.make_batch(T2_CHEMICAL, T2_LOT_EXPIRED, add_days(today(), -1))
	return T2_LOT_OK, T2_LOT_EXPIRED


def _t2_free(set_id):
	return not frappe.db.sql(
		"""select 1 from `tabWash Batch Set Unit` row join `tabWash Batch` batch on batch.name = row.parent
		where row.set_unit = %s and batch.docstatus = 0 and batch.status = 'Running' limit 1""",
		set_id,
	)


def _t2_candidates(set_type, status, wanted):
	"""Set ID của `set_type` có trạng thái `status`, chưa có Cycle ID, không ở lô đang chạy và cổng đúng `wanted`."""
	rows = frappe.get_all(
		"Set Unit",
		filters={"set_type": set_type, "status": status, "current_cycle_no": [">", 0]},
		fields=["name", "active_cycle_id"],
		order_by="creation asc, name asc",
	)
	out = []
	for row in rows:
		if row.active_cycle_id or not _t2_free(row.name):
			continue
		gates = {gate["step"]: gate["result"] for gate in step_gate.gates(row.name)}
		if all(gates[step] == result for step, result in wanted.items()):
			out.append(row.name)
	return out


def _t2_new_set(set_type, passed=(), fail_t2=False):
	unit = _issue_one(set_type)
	factories.make_cycle(unit, passed=passed)
	if fail_t2:
		step_gate.record(unit, "T2", "Fail")
	return unit


def _t2_operator():
	name = frappe.db.get_value("Employee", {"status": "Active"}, "name", order_by="creation asc, name asc")
	return name or factories.make_employee(card="DEMO-T2-OPERATOR").name


def ensure_t2_demo():
	"""Chuẩn bị màn T2 lô rửa (SCR-06) tại TR-002 trên site dev/test; idempotent, trả và in JSON các mã để quét.

	- ``machine``: máy rửa một cửa có bản in (Đạt không cần R02); ``machine_two_door``: máy hai cửa Bẩn → Sạch, có một
	  lô ``batch_running`` đang chạy; ``machine_locked``: máy đã ngừng sử dụng (``Retired``, từ chối 423);
	  ``machine_connected``: máy kết nối API (FEAT-021 vẫn nhập tay, Q13). Mỗi máy có một chương trình có hóa chất
	  ``DEMO-T2-ENZ`` và tham số (``program`` là chương trình của ``machine``).
	- ``sets``: 3 bộ loại hấp demo T4 đã qua T1, chưa ở lô nào; ``set_no_t1``: bộ chưa qua T1; ``set_redo``: bộ rửa
	  Không đạt (có trong hàng đợi xử lý lại).
	- ``chemical_lot_ok`` còn hạn, còn tồn; ``chemical_lot_expired`` đã hết hạn.
	Bộ đã được nạp/rửa được thay bằng bộ mới khi gọi lại.
	"""
	_require_dev_site()
	ensure_sample_templates()
	ensure_object_templates()
	lot_ok, lot_expired = _t2_chemical_lots()
	machine = _t2_machine("machine", has_printout=1)
	two_door = _t2_machine("machine_two_door", zone_out="ZONE-CLEAN", has_printout=1)
	locked = _t2_machine("machine_locked")
	connected = _t2_machine("machine_connected", is_connected=1, has_printout=1)
	if frappe.db.get_value("Equipment", locked, "status") != "Retired":
		equipment_status.set_status(locked, "Retired", "Demo T2: washer retired")
	programs = {key: _t2_program(name) for key, name in (("machine", machine), ("two_door", two_door))}
	_t2_program(connected)

	set_type = _ensure_set_type("Steam", _t4_catalog()["Steam"])
	ready = _t2_candidates(set_type, "Processing", {"T1": "Pass", "T2": "Pending"})
	while len(ready) < T2_READY_SETS:
		ready.append(_t2_new_set(set_type, passed=("T1",)))
	no_t1 = _t2_candidates(set_type, "Processing", {"T1": "Pending"})
	redo = _t2_candidates(set_type, "Reprocess", {"T1": "Pass", "T2": "Fail"})

	running = frappe.db.get_value(
		"Wash Batch",
		{"equipment": two_door, "status": "Running", "docstatus": 0},
		"name",
		order_by="creation asc, name asc",
	)
	if not running:
		running = washing.start(
			two_door,
			programs["two_door"],
			[_t2_new_set(set_type, passed=("T1",))],
			[{"item": T2_CHEMICAL, "lot": lot_ok}],
			T2_STATION,
			client_time.utc_now(),
			_t2_operator(),
		)["batch"]

	result = {
		"machine": machine,
		"machine_two_door": two_door,
		"machine_locked": locked,
		"machine_connected": connected,
		"program": programs["machine"],
		"sets": ready[:T2_READY_SETS],
		"set_no_t1": no_t1[0] if no_t1 else _t2_new_set(set_type),
		"set_redo": redo[0] if redo else _t2_new_set(set_type, passed=("T1",), fail_t2=True),
		"chemical_lot_ok": lot_ok,
		"chemical_lot_expired": lot_expired,
		"batch_running": running,
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo T5 nạp mẻ tiệt khuẩn (FEAT-022, SCR-09) ----------------------------------------------------------
T5_STATION = "TR-005"
# Mã loại bộ chỉ gồm 2-8 chữ hoa/số: DEMOT5S/DEMOT5P (tách khỏi DEMOT4*, e2e T4 đóng gói không lấy mất gói T5)
T5_SET_TYPES = {"Steam": "DEMOT5S", "Plasma": "DEMOT5P"}
T5_SERIALS = {
	"machine": "DEMO-T5-STEAM-01",
	"machine_plasma": "DEMO-T5-PLASMA-01",
	"machine_locked": "DEMO-T5-STEAM-LOCK",
	"machine_running": "DEMO-T5-STEAM-RUN",
}
T5_CAPACITY = "12"  # số gói tối đa mỗi mẻ (A-16 Q4)
T5_PARAMETERS = [
	{
		"parameter_name": "Sterilization temperature",
		"unit": "°C",
		"min_value": 132,
		"max_value": 138,
		"required": 1,
	},
	{"parameter_name": "Pressure", "unit": "bar", "min_value": 0, "max_value": 2.3, "required": 1},
	{"parameter_name": "Hold time", "unit": "min", "min_value": 3, "max_value": 0, "required": 1},
]
T5_READY_PACKS = 3


def _t5_machine(key, equipment_type, **fields):
	"""Máy tiệt khuẩn demo theo serial cố định (Equipment không xóa được nên dùng lại); trả TB-####."""
	name = frappe.db.get_value("Equipment", {"serial_no": T5_SERIALS[key]}, "name")
	if name:
		return name
	values = {
		"name": f"Demo sterilizer {key}",
		"equipment_type": equipment_type,
		"serial": T5_SERIALS[key],
		"manufacturer": EQ_MANUFACTURER,
		"model": "DEMO-S5",
		"capacity": T5_CAPACITY,
		**fields,
	}
	return factories.make_sterilizer(**values).name


def _t5_program(equipment):
	"""Chương trình tiệt khuẩn đang dùng đầu tiên của máy (tạo nếu chưa có), có tham số."""
	name = frappe.db.get_value(
		"Process Program", {"equipment": equipment, "is_active": 1}, "name", order_by="creation asc, name asc"
	)
	if name:
		return name
	code = "DEMO-T5-" + equipment.replace("TB-", "")
	return factories.make_sterilize_program(equipment, code=code, parameters=T5_PARAMETERS).name


def _t5_loadable(set_type, with_t4):
	"""Gói Packed demo của `set_type` còn hạn, còn là Cycle ID hiện hành, chưa ở mẻ nào; `with_t4` chọn cổng T4 Đạt hay chưa."""
	rows = frappe.get_all(
		"Pack",
		filters={"docstatus": 1, "status": "Packed", "set_type": set_type, "expiry": [">=", today()]},
		fields=["name", "set_unit", "cycle_no"],
		order_by="creation asc, name asc",
	)
	out = []
	for row in rows:
		unit = frappe.db.get_value(
			"Set Unit", row.set_unit, ["active_cycle_id", "current_cycle_no", "status"], as_dict=True
		)
		if unit.active_cycle_id != row.name or cint(unit.current_cycle_no) != cint(row.cycle_no):
			continue
		gates = {gate["step"]: gate["result"] for gate in step_gate.gates(row.set_unit)}
		if (gates["T4"] == "Pass") == with_t4 and gates["T5"] == "Pending":
			out.append(row.name)
	return out


def _t5_new_pack(method, with_t4=True):
	passed = ("T1", "T2", "T3", "T4") if with_t4 else ("T1", "T2", "T3")
	return factories.make_load_ready_pack(method=method, passed=passed, set_type=T5_SET_TYPES[method]).name


def ensure_t5_demo():
	"""Chuẩn bị màn T5 nạp mẻ (SCR-09) tại TR-005 trên site dev/test; idempotent, trả và in JSON các mã để quét.

	- ``machine``: máy hấp hơi nước hai cửa Sạch → Vô khuẩn, dung tích 12 gói, có bản in; ``machine_plasma``: máy
	  plasma; ``machine_locked``: máy hấp đã ngừng sử dụng (``Retired``, từ chối 423). ``program``/``program_plasma`` là
	  chương trình của hai máy đầu (có tham số cho form nhập tay).
	- ``packs``: 3 gói hơi nước (Cycle ID) đã qua T4, chưa ở mẻ nào; ``pack_plasma``: gói plasma (vào máy hấp bị
	  ``PACK_INCOMPATIBLE``); ``pack_no_t4``: gói hơi nước mà bộ chưa qua cổng T4.
	- ``load_running``: một mẻ ``Running`` trên ``machine_running`` (máy hấp riêng, để thử nhập dữ liệu chu trình):
	  máy còn mẻ chưa xong chu trình thì không nạp mẻ mới (A-22), nên ``machine`` để trống cho test nạp.
	Gói đã nạp/mẻ đã nhập dữ liệu được thay bằng gói/mẻ mới khi gọi lại.
	"""
	_require_dev_site()
	ensure_sample_templates()
	ensure_object_templates()
	machine = _t5_machine(
		"machine", "Steam Sterilizer", zone_in="ZONE-CLEAN", zone_out="ZONE-STERILE", has_printout=1
	)
	plasma = _t5_machine("machine_plasma", "Plasma Sterilizer", zone_in="ZONE-CLEAN", zone_out="ZONE-STERILE")
	locked = _t5_machine("machine_locked", "Steam Sterilizer", zone_in="ZONE-CLEAN", zone_out="ZONE-STERILE")
	if frappe.db.get_value("Equipment", locked, "status") != "Retired":
		equipment_status.set_status(locked, "Retired", "Demo T5: sterilizer retired")
	busy = _t5_machine(
		"machine_running", "Steam Sterilizer", zone_in="ZONE-CLEAN", zone_out="ZONE-STERILE", has_printout=1
	)
	program, program_plasma = _t5_program(machine), _t5_program(plasma)

	for method in T5_SET_TYPES:
		_ensure_set_type(method, _t4_catalog()[method], code=T5_SET_TYPES[method])
	steam_type, plasma_type = T5_SET_TYPES["Steam"], T5_SET_TYPES["Plasma"]
	ready = _t5_loadable(steam_type, with_t4=True)
	while len(ready) < T5_READY_PACKS + 1:  # +1: gói của mẻ đang chạy
		ready.append(_t5_new_pack("Steam"))
	plasma_packs = _t5_loadable(plasma_type, with_t4=True)
	no_t4 = _t5_loadable(steam_type, with_t4=False)

	running = frappe.db.get_value(
		"Sterilization Load",
		{"equipment": busy, "status": "Running", "docstatus": 0},
		"name",
		order_by="creation asc, name asc",
	)
	if not running:
		running = sterilizing.complete(
			busy, _t5_program(busy), [ready.pop()], T5_STATION, client_time.utc_now(), _t2_operator()
		)["load"]

	result = {
		"machine": machine,
		"machine_plasma": plasma,
		"machine_locked": locked,
		"machine_running": busy,
		"program": program,
		"program_plasma": program_plasma,
		"packs": ready[:T5_READY_PACKS],
		"pack_plasma": plasma_packs[0] if plasma_packs else _t5_new_pack("Plasma"),
		"pack_no_t4": no_t4[0] if no_t4 else _t5_new_pack("Steam", with_t4=False),
		"load_running": running,
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
	return frappe.db.get_value("Pack", filters, "name", order_by="creation asc, name asc")


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


# --- Demo T7 cấp phát (FEAT-026) ----------------------------------------------------------------------
T7_STATION = "TR-007"
T7_SET_TYPE = "DEMOT7S"
T7_SHELF = "DEMO-T7 Shelf"
T7_PIN = "246813"  # PIN của R02 duyệt vượt cơ số; chỉ ghi vào file env riêng tư của e2e
T7_PACKS = 8  # pack_1..pack_6 bị tiêu thụ theo thứ tự hạn, pack_fefo_near / pack_fefo_far chỉ quét thử FEFO
T7_DEPARTMENTS = {
	"dept": "DEMO-T7 Khoa A",
	"dept_tight": "DEMO-T7 Khoa B",
	"dept_open": "DEMO-T7 Khoa C",
	"dept_other": "DEMO-T7 Khoa D",
}
T7_EMPLOYEES = {
	"recipient": ("DEMO-T7 Nurse A", "dept"),
	"stranger": ("DEMO-T7 Nurse D", "dept_other"),
	"approver": ("DEMO-T7 R02 Supervisor", "dept_other"),
}


def ensure_t7_e2e_user(station, password):
	"""User kiosk trạm T7 (khu vô khuẩn → TC R06) và user R02 duyệt vượt cơ số, đăng ký OTP App như các trạm khác."""
	from tracecore.setup import provision

	_require_dev_site()
	_require_administrator()
	with _temporary_r10():
		user = provision.station_user(station, password)
		approver = provision.desk_user("TC R02", "r02-t7-e2e", password)
		return {"t7_user": user, "t7_otp_secret": _enroll_otp(user), "t7_approver_user": approver}


def _t7_employee(key, departments, approver_user=None):
	"""Nhân viên demo có thẻ (một lần theo tên); `approver` gắn User R02 và đặt PIN. Trả (Employee, thẻ)."""
	from tracecore.core import station_auth

	label, dept_key = T7_EMPLOYEES[key]
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	name = frappe.db.get_value("Employee", {"employee_name": label}, "name")
	employee = (
		frappe.get_doc("Employee", name)
		if name
		else frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": label,
				"gender": "Female",
				"date_of_birth": "1990-01-01",
				"date_of_joining": today(),
				"company": company,
			}
		)
	)
	employee.status = "Active"
	employee.department = departments[dept_key]
	employee.tc_card_enabled = 1
	employee.tc_card_id = employee.tc_card_id or f"T7-{secrets.token_hex(10)}".upper()
	if key == "approver" and approver_user:
		employee.user_id = approver_user
	employee.save(ignore_permissions=True)
	if key == "approver":
		station_auth.set_pin(employee.name, T7_PIN)
	return employee


def _t7_shelf():
	code = frappe.db.get_value(
		"Sterile Location", {"location_name": T7_SHELF, "zone_station": T6_STATION}, "name"
	)
	if not code:
		code = factories.make_sterile_location(T7_SHELF, T6_STATION).name
	if not frappe.db.get_value("Sterile Location", code, "is_active"):
		frappe.db.set_value("Sterile Location", code, "is_active", 1)
	return code


def _t7_stock():
	"""Gói demo T7 đang trong kho, chưa quá hạn và chưa nằm trong phiếu cấp phát, hạn sớm trước."""
	return frappe.db.sql_list(
		"""
		select p.name from `tabPack` p
		where p.docstatus = 1 and p.set_type = %s and p.status = 'In Sterile Stock' and p.expiry >= %s
		order by p.expiry asc, p.name asc
		""",
		(T7_SET_TYPE, today()),
	)


def _t7_par(set_type, department, min_qty, max_qty):
	if frappe.db.exists(
		"Par Level",
		{"par_kind": "Department Stock", "target": set_type, "department": department},
	):
		return
	factories.make_par_level(
		"Instrument Set Type",
		set_type,
		par_kind="Department Stock",
		department=department,
		min_qty=min_qty,
		max_qty=max_qty,
		is_active=1,
	)


def ensure_t7_demo(approver_user=None):
	"""Chuẩn bị màn T7 cấp phát (SCR-12/SCR-36) tại TR-007 trên site dev; idempotent, trả và in JSON các mã để quét.

	- ``dept``/``dept_name`` (cơ số tối đa 50), ``dept_tight``/``dept_tight_name`` (tối đa 1: cấp 2 gói là vượt, cần R02),
	  ``dept_open``/``dept_open_name`` (chưa cấu hình cơ số), ``dept_other``/``dept_other_name`` (khoa của người lạ).
	- ``recipient_card`` (nhân viên khoa ``dept``), ``stranger_card`` (khoa ``dept_other``), ``approver_card`` +
	  ``approver_pin`` (R02 khi ``approver_user`` được truyền).
	- ``pack_1``..``pack_6``: gói trong kho theo thứ tự hạn sớm trước (mỗi gói cấp một lần);
	  ``pack_fefo_near``/``pack_fefo_far``: hai gói hạn muộn nhất, chỉ quét thử FEFO; ``pack_released``: gói chưa nhập kho.
	Phiếu nháp cũ của các khoa demo bị xóa thẳng (chỉ trên site dev). Gói đã cấp được thay bằng gói mới khi gọi lại.
	"""
	from tracecore.reprocessing import storage

	_require_dev_site()
	_ensure_set_type("Steam", _t4_catalog()["Steam"], code=T7_SET_TYPE)
	departments = {key: factories.make_department(label) for key, label in T7_DEPARTMENTS.items()}
	names = {
		key: frappe.db.get_value("Department", name, "department_name") for key, name in departments.items()
	}
	_t7_par(T7_SET_TYPE, departments["dept"], 0, 50)
	_t7_par(T7_SET_TYPE, departments["dept_tight"], 0, 1)
	for dept in departments.values():
		drafts = frappe.get_all("Issue Note", filters={"docstatus": 0, "department": dept}, pluck="name")
		for draft in drafts:
			frappe.db.delete("Issue Note Pack", {"parent": draft})
			frappe.db.delete("Issue Note", {"name": draft})
	shelf = _t7_shelf()
	stock = _t7_stock()
	for index in range(len(stock), T7_PACKS):
		pack = factories.make_released_pack(expiry_days=20 + 2 * index + len(stock), set_type=T7_SET_TYPE)
		storage.putaway(pack.name, shelf, T6_STATION)
		stock = _t7_stock()
	packs = stock[:T7_PACKS]
	near, far = packs[-2], packs[-1]
	if frappe.db.get_value("Pack", near, "expiry") == frappe.db.get_value("Pack", far, "expiry"):
		frappe.db.set_value("Pack", far, "expiry", add_days(frappe.db.get_value("Pack", far, "expiry"), 1))
	released = (
		frappe.db.get_value(
			"Pack",
			{"docstatus": 1, "set_type": T7_SET_TYPE, "status": "Released", "expiry": [">", today()]},
			"name",
			order_by="creation asc, name asc",
		)
		or factories.make_released_pack(set_type=T7_SET_TYPE).name
	)
	cards = {}
	for key in T7_EMPLOYEES:
		employee = _t7_employee(key, departments, approver_user)
		cards[f"{key}_card"] = employee.tc_card_id
	result = {
		**{key: value for key, value in departments.items()},
		**{f"{key}_name": value for key, value in names.items()},
		**cards,
		"approver_pin": T7_PIN,
		**{f"pack_{i}": packs[i - 1] for i in range(1, 7)},
		"pack_fefo_near": near,
		"pack_fefo_far": far,
		"pack_released": released,
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo T3 kiểm đếm lắp ráp (FEAT-020) --------------------------------------------------------------
T3_STATION = "TR-003"
T3_SET_TYPE = "DEMOT3S"
T3_READY = ("set_full", "set_short", "set_branch")
SMOKE_STATION = (
	"TR-090"  # trạm tra cứu Set ID chung (không bước) cho smoke FEAT-001, vì TR-003 đã có màn T3 riêng
)


def ensure_smoke_station(station=SMOKE_STATION):
	"""Trạm khu sạch không gán bước (màn tra cứu Set ID chung) cho e2e smoke FEAT-001; idempotent, trả mã trạm.

	Mỗi trạm bước T1..T7 dần có màn riêng nên smoke không thể đặt ở trạm có bước. Trạm không bước vẫn đăng nhập thẻ được
	và dùng `v1.set_unit.get`.
	"""
	_require_dev_site()
	if not frappe.db.exists("Zone Station", station):
		frappe.get_doc(
			{
				"doctype": "Zone Station",
				"is_zone": 0,
				"is_active": 1,
				"zone_station_name": "Set lookup (smoke)",
				"parent_zone": "ZONE-CLEAN",
			}
		).insert(ignore_permissions=True, set_name=station)
	return station


def ensure_t3_e2e_users(station, password):
	"""User kiosk trạm T3 (khu sạch → TC R04) và user R02 cho PIN xác nhận thiếu (FEAT-020); đăng ký OTP App cho user kiosk.

	R02 chỉ cần Employee + thẻ + năng lực (`ensure_t3_r02`), không đăng nhập Desk. Bí mật chỉ ghi vào file env riêng tư.
	"""
	from tracecore.setup import provision

	_require_dev_site()
	_require_administrator()
	with _temporary_r10():
		user = provision.station_user(station, password)
		r02 = provision.desk_user("TC R02", "r02-t3-e2e", password)
		return {"t3_user": user, "t3_otp_secret": _enroll_otp(user), "t3_r02_user": r02}


def ensure_t3_r02(station, user):
	"""Thẻ + năng lực tại `station` cho user R02 và một PIN 6 số ngẫu nhiên mới; trả ``{employee, card_id, pin}``.

	PIN đổi mỗi lần chạy (không có PIN cố định); chỉ ghi vào file env riêng tư của e2e.
	"""
	import secrets as secrets_module

	from tracecore.core import station_auth

	card = ensure_station_demo(station, user)
	pin = f"{secrets_module.randbelow(10**6):06d}"
	station_auth.set_pin(card["employee"], pin)
	frappe.db.set_value("Employee", card["employee"], "tc_pin_reset_required", 0)
	return {"employee": card["employee"], "card_id": card["card_id"], "pin": pin}


def _t3_counted(set_id):
	"""Bộ đã có phiếu lắp ráp (bản nháp hay ghi sổ) trong chu trình hiện hành."""
	return bool(
		frappe.db.exists(
			"Assembly Record",
			{
				"set_unit": set_id,
				"cycle_no": frappe.db.get_value("Set Unit", set_id, "current_cycle_no"),
			},
		)
	)


def _t3_candidates(set_type, wanted):
	rows = frappe.get_all(
		"Set Unit",
		filters={"set_type": set_type, "status": "Processing", "current_cycle_no": [">", 0]},
		fields=["name", "active_cycle_id"],
		order_by="creation asc, name asc",
	)
	out = []
	for row in rows:
		if row.active_cycle_id or _t3_counted(row.name):
			continue
		gates = {gate["step"]: gate["result"] for gate in step_gate.gates(row.name)}
		if all(gates[step] == result for step, result in wanted.items()):
			out.append(row.name)
	return out


def ensure_t3_demo():
	"""Chuẩn bị màn T3 kiểm đếm lắp ráp (SCR-07) tại TR-003 trên site dev/test; idempotent, trả và in JSON các mã để quét.

	- ``set_full``, ``set_short``, ``set_branch``: ba bộ loại hấp ``DEMOT3S`` (BOM 4 dụng cụ có ảnh, 3 ảnh khay) đã qua
	  T1-T2, chưa có phiếu lắp ráp: đếm đủ → T3 Đạt; đếm thiếu → R02 PIN; rẽ nhánh Sửa chữa/Thanh lý.
	- ``set_no_wash``: bộ mới qua T1, chưa qua lô rửa (T2 Chưa): T3 từ chối ``GATE_PREV_NOT_PASSED``.
	- ``short_instrument``: dụng cụ (BOM, số lượng 2) để ghi thiếu.
	Bộ đã được đếm/ghi sổ được thay bằng bộ mới khi gọi lại.
	"""
	_require_dev_site()
	set_type = _ensure_set_type("Steam", _t4_catalog()["Steam"], code=T3_SET_TYPE)
	ready = _t3_candidates(set_type, {"T1": "Pass", "T2": "Pass", "T3": "Pending"})
	while len(ready) < len(T3_READY):
		ready.append(_t2_new_set(set_type, passed=("T1", "T2")))
	no_wash = _t3_candidates(set_type, {"T1": "Pass", "T2": "Pending"})
	result = {
		**dict(zip(T3_READY, ready, strict=False)),
		"set_no_wash": no_wash[0] if no_wash else _t2_new_set(set_type, passed=("T1",)),
		"short_instrument": _t4_catalog()["Steam"]["bom"][0][0],
	}
	print(json.dumps(result, sort_keys=True))
	return result


# --- Demo T1 tiếp nhận (FEAT-019) ---------------------------------------------------------------------
T1_STATION = "TR-001"
T1_SET_TYPE = "DEMOT1S"
T1_DELIVERER_CARD = "DEMO-T1-DELIVERER"
T1_READY_SETS = 3  # bộ Chờ tiếp nhận cho luồng nhiều bộ nối tiếp
T1_NEW_SETS = 3  # bộ Mới tạo: một cho luồng chính, hai cho PDA


def ensure_t1_e2e_user(station, password):
	"""User kiosk trạm T1 (khu bẩn → TC R03) cho e2e màn tiếp nhận (FEAT-019), đăng ký OTP App.

	Tách khỏi `ensure_e2e_users` để không đổi khóa trả về của hàm đó; bí mật chỉ ghi vào file env riêng tư của e2e.
	"""
	from tracecore.setup import provision

	_require_dev_site()
	_require_administrator()
	with _temporary_r10():
		user = provision.station_user(station, password)
		return {"t1_user": user, "t1_otp_secret": _enroll_otp(user)}


def _t1_deliverer():
	"""Nhân viên khoa demo có thẻ đã bật (người giao ở T1); dùng lại nếu đã có. Trả Employee."""
	from tracecore.core.station_auth import normalize_card_id

	card = normalize_card_id(T1_DELIVERER_CARD)
	name = frappe.db.get_value("Employee", {"tc_card_id": card}, "name")
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if not name and not company:
		frappe.throw(_("Complete company setup before creating demo employees."))
	employee = (
		frappe.get_doc("Employee", name)
		if name
		else frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": _("Demo ward deliverer", lang="vi"),
				"gender": "Female",
				"date_of_birth": "1992-01-01",
				"date_of_joining": today(),
				"company": company,
				"tc_card_id": card,
			}
		)
	)
	employee.status = "Active"
	employee.tc_card_enabled = 1
	employee.department = _demo_department()
	employee.save(ignore_permissions=True)
	return employee


def _t1_sets(set_type, status):
	return frappe.get_all(
		"Set Unit",
		filters={"set_type": set_type, "status": status, "active_cycle_id": ["is", "not set"]},
		pluck="name",
		order_by="creation asc, name asc",
	)


def _t1_awaiting_set(set_type):
	"""Bộ Chờ tiếp nhận hợp lệ: đi hết năm cổng rồi trả về khu bẩn (`step_gate.return_to_receipt`, FR-M2-14)."""
	unit = _issue_one(set_type)
	factories.make_cycle(unit, passed=factories.ALL_GATES)
	step_gate.return_to_receipt(unit)
	return unit


def ensure_t1_demo():
	"""Chuẩn bị màn T1 tiếp nhận (SCR-05) tại TR-001 trên site dev/test; idempotent, trả và in JSON các mã để quét.

	- ``deliverer_card``, ``deliverer_name``, ``department``: thẻ người giao (nhân viên khoa demo) và khoa suy ra từ thẻ.
	- ``sets``: 3 bộ Chờ tiếp nhận (đã đi hết chu trình rồi trả về) cho luồng nhiều bộ nối tiếp; ``set_new``: 1 bộ
	  Mới tạo; ``sets_pda``: 2 bộ Mới tạo cho PDA. Cả sáu bộ có BOM 4 dụng cụ kèm ảnh demo.
	- ``set_sterile``: bộ Vô khuẩn, T1 từ chối ``STATUS_INVALID_FOR_STATION``.
	- ``set_unknown``: Set ID đúng định dạng GIAI nhưng chưa cấp (mã không hợp lệ).
	Bộ đã được tiếp nhận (đã mở chu trình) được thay bằng bộ mới khi gọi lại.
	"""
	_require_dev_site()
	set_type = _ensure_set_type("Steam", _t4_catalog()["Steam"], code=T1_SET_TYPE)
	deliverer = _t1_deliverer()
	awaiting = _t1_sets(set_type, "Awaiting Receipt")[:T1_READY_SETS]
	while len(awaiting) < T1_READY_SETS:
		awaiting.append(_t1_awaiting_set(set_type))
	new = _t1_sets(set_type, "New")
	new = [name for name in new if not frappe.db.get_value("Set Unit", name, "current_cycle_no")][
		:T1_NEW_SETS
	]
	while len(new) < T1_NEW_SETS:
		new.append(_issue_one(set_type))
	sterile = _t1_sets(set_type, "Sterile")
	if not sterile:
		unit = _issue_one(set_type)
		factories.make_cycle(unit, passed=factories.ALL_GATES)
		sterile = [unit]
	result = {
		"department": deliverer.department,
		"deliverer_card": deliverer.tc_card_id,
		"deliverer_name": deliverer.employee_name,
		"sets": awaiting,
		"set_new": new[0],
		"sets_pda": new[1:],
		"set_sterile": sterile[0],
		"set_unknown": gs1.make_giai(gs1.configured_company_prefix(), f"{T1_SET_TYPE}999999"),
	}
	print(json.dumps(result, sort_keys=True))
	return result
