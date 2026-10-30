"""Mẫu nhãn mẫu (Label Template): nhãn gói (FEAT-018 Task 5), nhãn QR đối tượng (FEAT-005 Task 2), thẻ kim loại và
nhãn khay của bộ dụng cụ (FEAT-016 Task 3, G8).

Tạo bằng hàm, không bằng fixtures.

`bench migrate` ghi đè fixtures bằng bản trong repo nên mẫu R10 đã chỉnh sẽ mất; vì vậy mẫu mẫu chỉ được
tạo NẾU CHƯA CÓ (`after_install` và patch cho site đã cài), và không bao giờ ghi đè (FR-M2-08.4).
"""

import json
import os
from datetime import date

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core import print as core_print

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "label_templates")
SAMPLE_DOC_PATH = os.path.join(TEMPLATE_DIR, "pack_sample.json")
OBJECT_SAMPLE_PATH = os.path.join(TEMPLATE_DIR, "object_sample.json")
SET_SAMPLE_PATH = os.path.join(TEMPLATE_DIR, "set_sample.json")

# Mẫu đầu: 60 x 40 mm, 300 dpi, ZPL (D7)
SAMPLE_TEMPLATES = (
	{"template_name": "Pack label - Steam", "method": "Steam", "file": "pack_steam.zpl.jinja"},
	{"template_name": "Pack label - Plasma", "method": "Plasma", "file": "pack_plasma.zpl.jinja"},
)
SAMPLE_SIZE = {"width_mm": 60, "height_mm": 40, "dpi": 300}
SAMPLE_GTIN_SERIAL = 1
SAMPLE_PACKED = date(2026, 10, 20)
SAMPLE_EXPIRY = date(2026, 11, 19)

# Nhãn QR đối tượng (A-05 R2): 50 x 30 mm, 300 dpi, ZPL, một file mẫu chung; không có phương pháp tiệt khuẩn
OBJECT_TEMPLATE_FILE = "object_qr.zpl.jinja"
OBJECT_TEMPLATES = tuple(
	{"template_name": f"Object label - {label_object}", "label_object": label_object}
	for label_object in core_print.OBJECT_LABELS
)
OBJECT_SIZE = {"width_mm": 50, "height_mm": 30, "dpi": 300}

# Thẻ kim loại 50 x 30 mm và nhãn khay 60 x 40 mm, 300 dpi, ZPL (G8); không có phương pháp tiệt khuẩn
SET_TEMPLATES = (
	{
		"template_name": "Set tag",
		"label_object": "Set Tag",
		"file": "set_tag.zpl.jinja",
		"size": {"width_mm": 50, "height_mm": 30, "dpi": 300},
	},
	{
		"template_name": "Set tray label",
		"label_object": "Set Tray Label",
		"file": "set_tray.zpl.jinja",
		"size": {"width_mm": 60, "height_mm": 40, "dpi": 300},
	},
)


def _ensure_templates(rows) -> list[str]:
	"""Tạo các mẫu (template_name, label_object, method, file, kích thước) còn thiếu; trả tên mẫu vừa tạo.

	Mẫu đã có (kể cả bản R10 đã sửa) giữ nguyên. Nếu R10 đã có mẫu khác đang active cho cùng
	(đối tượng, phương pháp, ngôn ngữ) thì mẫu mẫu được tạo ở trạng thái không active để không tranh chỗ.
	"""
	created = []
	for row in rows:
		name = row["template_name"]
		if frappe.db.exists("Label Template", name):
			continue
		method = row.get("method")
		slot = {
			"label_object": row["label_object"],
			"method": core_print.method_filter(method),
			"language": "ZPL",
			"is_active": 1,
		}
		with open(os.path.join(TEMPLATE_DIR, row["file"]), encoding="utf-8") as handle:
			body = handle.read()
		frappe.get_doc(
			{
				"doctype": "Label Template",
				"template_name": name,
				"label_object": row["label_object"],
				"method": method,
				"language": "ZPL",
				"is_active": 0 if frappe.db.exists("Label Template", slot) else 1,
				**row["size"],
				"body": body,
			}
		).insert(ignore_permissions=True)
		created.append(name)
	return created


def ensure_sample_templates() -> list[str]:
	"""Tạo mẫu nhãn gói mẫu còn thiếu (không ghi đè, không tranh chỗ active); trả tên các mẫu vừa tạo."""
	return _ensure_templates(
		{**sample, "label_object": "Pack", "size": SAMPLE_SIZE} for sample in SAMPLE_TEMPLATES
	)


def ensure_object_templates() -> list[str]:
	"""Tạo mẫu nhãn QR đối tượng `Object label - …` còn thiếu (không ghi đè, không tranh chỗ active)."""
	return _ensure_templates(
		{**sample, "file": OBJECT_TEMPLATE_FILE, "size": OBJECT_SIZE} for sample in OBJECT_TEMPLATES
	)


def ensure_set_templates() -> list[str]:
	"""Tạo mẫu thẻ kim loại / nhãn khay (`SET_TEMPLATES`) còn thiếu (không ghi đè, không tranh chỗ active)."""
	return _ensure_templates(SET_TEMPLATES)


def sample_pack_context(**overrides) -> dict:
	"""`doc` đầy đủ cho mẫu nhãn gói: dùng cho test và xem trước mẫu.

	GTIN là GTIN TEST (`gs1.make_test_gtin14`) nên `is_test` bật; chữ tiếng Việt có dấu để thử cả hai
	chế độ in (`unicode` bật/tắt). `overrides` ghi đè từng khóa, không tính lại `payload`/`hri`.
	"""
	with open(SAMPLE_DOC_PATH, encoding="utf-8") as handle:
		doc = json.load(handle)
	gtin = gs1.make_test_gtin14(SAMPLE_GTIN_SERIAL)
	args = (gtin, SAMPLE_PACKED, SAMPLE_EXPIRY, doc["cycle_id"])
	doc.update(
		is_test=gs1.is_test_gtin(gtin),
		payload=gs1.make_cycle_payload(*args),
		hri=gs1.cycle_hri(*args),
	)
	doc.update(overrides)
	return doc


def sample_object_context(label_object) -> dict:
	"""`doc` mẫu cho nhãn QR đối tượng (`code, title, subtitle, payload, is_test`): dùng cho test và xem trước.

	Mã mẫu đúng định dạng §5.3.3 của loại đối tượng (không ghi Code Registry); tên có dấu để thử cả hai chế độ in.
	"""
	with open(OBJECT_SAMPLE_PATH, encoding="utf-8") as handle:
		samples = json.load(handle)
	if label_object not in core_print.OBJECT_LABELS or label_object not in samples:
		frappe.throw(_("Label object {0} has no QR label.").format(label_object))
	sample = samples[label_object]
	return {
		**core_print.object_context(label_object, sample["code"], sample["title"], sample["subtitle"]),
		"is_test": True,
	}


def sample_set_context(label_object) -> dict:
	"""`doc` mẫu cho thẻ kim loại / nhãn khay, cùng khóa với `instrument.set_tags.tag_context`: dùng cho test, dựng thử
	khi lưu mẫu và xem trước.

	Set ID mẫu mang tiền tố GS1 demo (`gs1.DEFAULT_COMPANY_PREFIX`, không ghi Code Registry) nên `is_test` bật; bộ cấy
	ghép và tên có dấu để thử mọi nhánh của mẫu ở cả hai chế độ in.
	"""
	if label_object not in core_print.SET_LABELS:
		frappe.throw(_("Label object {0} is not a set tag or tray label.").format(label_object))
	with open(SET_SAMPLE_PATH, encoding="utf-8") as handle:
		sample = json.load(handle)
	set_id = gs1.make_giai(gs1.DEFAULT_COMPANY_PREFIX, sample["type_code"] + sample.pop("serial"))
	return {
		"set_id": set_id,
		"payload": gs1.giai_payload(set_id),
		"hri": gs1.giai_hri(set_id),
		**sample,
		"is_test": gs1.is_demo_prefix(set_id),
	}


def sample_context(label_object) -> dict:
	"""Dữ liệu mẫu theo loại đối tượng của mẫu nhãn: nhãn gói, thẻ/nhãn khay bộ dụng cụ hoặc nhãn QR đối tượng."""
	if label_object == "Pack":
		return sample_pack_context()
	if label_object in core_print.SET_LABELS:
		return sample_set_context(label_object)
	return sample_object_context(label_object)
