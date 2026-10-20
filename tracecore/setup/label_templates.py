"""Mẫu nhãn mẫu (Label Template) cho nhãn gói: tạo bằng hàm, không bằng fixtures (FEAT-018 Task 5).

`bench migrate` ghi đè fixtures bằng bản trong repo nên mẫu R10 đã chỉnh sẽ mất; vì vậy mẫu mẫu chỉ được
tạo NẾU CHƯA CÓ (`after_install` và patch cho site đã cài), và không bao giờ ghi đè (FR-M2-08.4).
"""

import json
import os
from datetime import date

import frappe

from tracecore.core import gs1

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "label_templates")
SAMPLE_DOC_PATH = os.path.join(TEMPLATE_DIR, "pack_sample.json")

# Mẫu đầu: 60 x 40 mm, 300 dpi, ZPL (D7)
SAMPLE_TEMPLATES = (
	{"template_name": "Pack label - Steam", "method": "Steam", "file": "pack_steam.zpl.jinja"},
	{"template_name": "Pack label - Plasma", "method": "Plasma", "file": "pack_plasma.zpl.jinja"},
)
SAMPLE_SIZE = {"width_mm": 60, "height_mm": 40, "dpi": 300}
SAMPLE_GTIN_SERIAL = 1
SAMPLE_PACKED = date(2026, 10, 20)
SAMPLE_EXPIRY = date(2026, 11, 19)


def ensure_sample_templates() -> list[str]:
	"""Tạo mẫu nhãn mẫu còn thiếu; trả tên các mẫu vừa tạo.

	Mẫu đã có (kể cả bản R10 đã sửa) giữ nguyên. Nếu R10 đã có mẫu khác đang active cho cùng
	(đối tượng, phương pháp, ngôn ngữ) thì mẫu mẫu được tạo ở trạng thái không active để không tranh chỗ.
	"""
	created = []
	for sample in SAMPLE_TEMPLATES:
		name = sample["template_name"]
		if frappe.db.exists("Label Template", name):
			continue
		slot = {"label_object": "Pack", "method": sample["method"], "language": "ZPL", "is_active": 1}
		with open(os.path.join(TEMPLATE_DIR, sample["file"]), encoding="utf-8") as handle:
			body = handle.read()
		frappe.get_doc(
			{
				"doctype": "Label Template",
				"template_name": name,
				**slot,
				"is_active": 0 if frappe.db.exists("Label Template", slot) else 1,
				**SAMPLE_SIZE,
				"body": body,
			}
		).insert(ignore_permissions=True)
		created.append(name)
	return created


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
