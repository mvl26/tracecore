"""A-155 (P6): tách giấy bọc khỏi vải bọc, suy số lớp giấy bọc và kích thước túi ép từ tên loại gói.

Chỉ đụng Item nhóm `Packaging`:

* nhóm vật liệu `Wrap` hoặc trống mà tên có "giấy" / "crepe" / "paper" → `Paper Wrap`;
* `Paper Wrap` chưa có số lớp mà tên có "1 lớp" / "2 lớp" → `Single Layer` / `Double Layer`;
* `Sealed Pouch` chưa có kích thước mà tên có "rộng x dài" (mm) → kích thước chuẩn hóa (`100 x 250`, dấu nhân U+00D7).

Không suy được thì để trống cho R10 nhập (T4 vẫn dùng được; lưu lại Item mới bắt nhập). Giá trị đã có giữ nguyên;
chạy lại không đổi gì thêm. Ghi thẳng bằng ``db.set_value`` (không chạy validate của Item), không đổi Pack đã đóng.
Patch chạy trước khi `migrate` đồng bộ fixtures nên tự tạo/cập nhật Custom Field (cùng định nghĩa với
`fixtures/custom_field.json`) khi cột chưa có.
"""

import json
import re

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tracecore.inventory.items import normalize_pouch_size
from tracecore.patches.v0_1.a122_pack_material import _plain

FIELDS = ("Item-tc_pack_material", "Item-tc_pouch_size", "Item-tc_wrap_layers")
WRAP, POUCH, PAPER = "Wrap", "Sealed Pouch", "Paper Wrap"
PAPER_WORDS = ("giay", "crepe", "paper")
LAYERS = (("1 lop", "Single Layer"), ("2 lop", "Double Layer"))
_SIZE_IN_NAME = re.compile(r"\b(\d{2,4}\s*[x\u00d7*]\s*\d{2,4})\b", re.IGNORECASE)


def is_paper(item_name):
	name = _plain(item_name)
	return any(re.search(rf"\b{word}\b", name) for word in PAPER_WORDS)


def layers_from_name(item_name):
	name = re.sub(r"\s+", " ", _plain(item_name))
	for words, value in LAYERS:
		if re.search(rf"\b{words}\b", name):
			return value
	return None


def pouch_size_from_name(item_name):
	match = _SIZE_IN_NAME.search(item_name or "")
	return normalize_pouch_size(match.group(1)) if match else None


def _ensure_fields():
	path = frappe.get_app_path("tracecore", "fixtures", "custom_field.json")
	with open(path, encoding="utf-8") as handle:
		rows = {row["name"]: row for row in json.load(handle)}
	create_custom_fields(
		{
			"Item": [
				{key: value for key, value in rows[name].items() if key not in ("doctype", "dt", "name")}
				for name in FIELDS
			]
		},
		update=True,
	)


def execute():
	if not all(
		frappe.db.has_column("Item", column)
		for column in ("tc_pack_material", "tc_pouch_size", "tc_wrap_layers")
	):
		_ensure_fields()
	for row in frappe.get_all(
		"Item",
		filters={"tc_item_group_cssd": "Packaging"},
		fields=["name", "item_name", "tc_pack_material", "tc_pouch_size", "tc_wrap_layers"],
	):
		changes = {}
		material = row.tc_pack_material or ""
		if material in ("", WRAP) and is_paper(row.item_name):
			material = changes["tc_pack_material"] = PAPER
		if material == PAPER and not row.tc_wrap_layers:
			layers = layers_from_name(row.item_name)
			if layers:
				changes["tc_wrap_layers"] = layers
		if material == POUCH and not row.tc_pouch_size:
			size = pouch_size_from_name(row.item_name)
			if size:
				changes["tc_pouch_size"] = size
		if changes:
			frappe.db.set_value("Item", row.name, changes, update_modified=False)
