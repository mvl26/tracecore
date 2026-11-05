"""A-122: điền nhóm vật liệu gói (`Item.tc_pack_material`) cho loại gói đã có để T4 dựng droplist có nhóm.

Chỉ đụng Item nhóm `Packaging` còn để trống nhóm vật liệu: xét tiền tố mã trước (`PK-HOP` → hộp hấp, `PK-TUI` → túi ép,
`PK-VKD`/`PK-XV`/`PK-VAI` → vải gói), rồi từ khóa trong tên. Không khớp thì để trống cho R10 phân nhóm tay. Item đã có nhóm
giữ nguyên; chạy lại không đổi gì thêm. Không đổi Pack đã đóng.

Patch chạy trước khi `migrate` đồng bộ fixtures nên tự tạo Custom Field (cùng định nghĩa với `fixtures/custom_field.json`)
khi cột chưa có.
"""

import json
import re
import unicodedata

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELD = "Item-tc_pack_material"
CONTAINER, POUCH, WRAP = "Rigid Container", "Sealed Pouch", "Wrap"
CODE_PREFIXES = (
	("PK-HOP", CONTAINER),
	("PK-TUI", POUCH),
	("PK-VKD", WRAP),
	("PK-XV", WRAP),
	("PK-VAI", WRAP),
)
# từ khóa tên đã bỏ dấu (so trên tên chuẩn hóa không dấu, chữ thường), xét theo thứ tự
NAME_KEYWORDS = (
	(("hop",), CONTAINER),
	(("tui", "tyvek"), POUCH),
	(("vai", "xang", "khong det", "sms", "crepe"), WRAP),
)


def _plain(text):
	"""Chữ thường, bỏ dấu tiếng Việt (kể cả đ → d)."""
	decomposed = unicodedata.normalize("NFD", (text or "").lower().replace(chr(0x111), "d"))  # chr(0x111) = đ
	return "".join(char for char in decomposed if not unicodedata.combining(char))


def classify(code, item_name):
	"""Nhóm vật liệu suy từ mã rồi tên; không suy được thì ``None``."""
	upper = (code or "").upper()
	for prefix, material in CODE_PREFIXES:
		if upper.startswith(prefix):
			return material
	name = _plain(item_name)
	for words, material in NAME_KEYWORDS:
		if any(re.search(rf"\b{re.escape(word)}\b", name) for word in words):
			return material
	return None


def _field_definition():
	path = frappe.get_app_path("tracecore", "fixtures", "custom_field.json")
	with open(path, encoding="utf-8") as handle:
		row = next(item for item in json.load(handle) if item["name"] == FIELD)
	return {key: value for key, value in row.items() if key not in ("doctype", "dt", "name")}


def execute():
	if not frappe.db.has_column("Item", "tc_pack_material"):
		create_custom_fields({"Item": [_field_definition()]}, update=True)
	for row in frappe.get_all(
		"Item",
		filters={"tc_item_group_cssd": "Packaging", "tc_pack_material": ["in", ["", None]]},
		fields=["name", "item_name"],
	):
		material = classify(row.name, row.item_name)
		if material:
			frappe.db.set_value("Item", row.name, "tc_pack_material", material, update_modified=False)
