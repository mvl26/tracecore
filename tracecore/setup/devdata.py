"""Dữ liệu demo cho site dev/test (developer_mode hoặc allow_tests; không chạy trên production).

- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_demo_set`` in Set ID GIAI thử để quét ở /app/station.
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_t4_demo`` chuẩn bị màn T4 đóng gói (SCR-08) tại
  TR-004 và in JSON các mã để quét (bộ hấp, bộ plasma, bộ chưa qua cổng T3, lô chỉ thị, mã cuộn nhãn, máy in).
- ``bench --site <SITE> execute tracecore.setup.devdata.ensure_equipment_demo`` chuẩn bị máy và chương trình xử lý
  cho e2e Desk SCR-21 (FEAT-038) và in JSON các mã (tên máy, mã chương trình).
"""

import io
import json

import frappe
from frappe import _
from frappe.utils import add_days, today

from tracecore.core import code_registry, gs1, step_gate
from tracecore.core import print as core_print
from tracecore.equipment import status as equipment_status
from tracecore.setup.label_templates import ensure_sample_templates
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
DEMO_OIL_LOT = "DEMO-T4-DAU-01"  # lô dầu để xác nhận "Đã bảo dưỡng" cho nhắc tra dầu
STEAM_LABEL, PLASMA_LABEL = (code for code, _method in factories.LABEL_ITEMS)
T4_GATES_READY = ("T1", "T2", "T3")
T4_GATES_FAIL = ("T1", "T2")  # chưa có cổng T3 Đạt → T4 từ chối GATE_PREV_NOT_PASSED


def _require_dev_site():
	if not (frappe.conf.get("developer_mode") or frappe.conf.get("allow_tests") or frappe.flags.in_test):
		frappe.throw(_("Demo data can only be created on a developer or test site."))


def ensure_demo_set():
	"""Tạo (nếu chưa có) loại bộ DEMO và một Set Unit; trả và in Set ID."""
	_require_dev_site()
	if not frappe.db.exists("Instrument Set Type", DEMO_SET_TYPE):
		frappe.get_doc(
			{
				"doctype": "Instrument Set Type",
				"type_code": DEMO_SET_TYPE,
				"set_type_name": "Demo set",
				"method": "Steam",
			}
		).insert(ignore_permissions=True)
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


def _ensure_instrument(code, name):
	if not frappe.db.exists("Instrument", code):
		lube = code == T4_LUBE_INSTRUMENT
		factories.make_instrument(
			code,
			name,
			interval=T4_LUBE_INTERVAL if lube else None,
			maint_type="Lubrication" if lube else None,
			image=_demo_image(code),
		)
	elif not frappe.db.get_value("Instrument", code, "image"):
		frappe.db.set_value("Instrument", code, "image", _demo_image(code))


def _ensure_set_type(method, spec):
	"""Loại bộ demo (GTIN test, loại gói mặc định, ảnh khay) và BOM phiên bản 1; trả mã loại bộ."""
	code = T4_SET_TYPES[method]
	pack_code, pack_name, days = spec["pack_type"]
	if not frappe.db.exists("Item", pack_code):
		factories.make_item(pack_code, "Packaging", shelf_life_days=days)
		frappe.db.set_value("Item", pack_code, "item_name", pack_name)
	for instrument, name, _qty in spec["bom"]:
		_ensure_instrument(instrument, name)
	if not frappe.db.exists("Instrument Set Type", code):
		frappe.get_doc(
			{
				"doctype": "Instrument Set Type",
				"type_code": code,
				"set_type_name": spec["set_name"],
				"method": method,
				"gtin": _free_demo_gtin(),
				"default_pack_type": pack_code,
				"tray_image": _demo_image(f"{code}-TRAY"),
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("Set BOM Item", {"set_type": code, "bom_version": 1}):
		factories.make_bom(code, [(instrument, qty) for instrument, _name, qty in spec["bom"]])
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
