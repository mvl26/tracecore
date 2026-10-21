"""Danh mục dụng cụ đơn lẻ (M1, FEAT-014; A-06 I2, I9, I10).

Mã dụng cụ chuẩn hóa NFKC → bỏ khoảng trắng đầu/cuối → viết hoa → ``[A-Z0-9-]{1,40}``. Trùng mã (kể cả dụng cụ đã
Ngừng sử dụng) báo kèm mã kế tiếp còn trống. Phương pháp tương thích lưu ở bảng con ``Instrument Compatible Method``;
họ phương pháp (``Steam``/``Plasma``/``EO``) dùng để so với ``Instrument Set Type.method``.
"""

import re
import unicodedata
from collections.abc import Iterable

import frappe
from frappe import _
from frappe.model.document import Document

METHODS: tuple[str, ...] = ("Steam 121", "Steam 134", "Plasma", "EO")
METHOD_FAMILY: dict[str, str] = {"Steam 121": "Steam", "Steam 134": "Steam", "Plasma": "Plasma", "EO": "EO"}

CODE_MAX_LENGTH = 40
CODE_PATTERN = re.compile(rf"[A-Z0-9-]{{1,{CODE_MAX_LENGTH}}}")
SUGGEST_ATTEMPTS = 1000
_TRAILING_DIGITS = re.compile(r"^(.*?)([0-9]+)$")


def normalize_code(code: str) -> str:
	"""Mã dụng cụ chuẩn; mã rỗng, có ký tự ngoài ``A-Z 0-9 -`` hoặc dài quá 40 ký tự → ValidationError."""
	text = unicodedata.normalize("NFKC", code or "").strip().upper()
	if not CODE_PATTERN.fullmatch(text):
		frappe.throw(
			_(
				"Instrument Code may contain only uppercase letters, digits and hyphens, at most {0} characters."
			).format(CODE_MAX_LENGTH)
		)
	return text


def code_exists(code: str) -> bool:
	return bool(frappe.db.exists("Instrument", code))


def _codes_with_prefix(prefix: str) -> set[str]:
	# mã chỉ gồm A-Z 0-9 - nên tiền tố không chứa ký tự đại diện của LIKE
	return set(frappe.get_all("Instrument", filters={"name": ["like", f"{prefix}%"]}, pluck="name"))


def suggest_code(code: str) -> str:
	"""Mã kế tiếp còn trống sau `code` (I10).

	Phần số cuối +1, giữ độ rộng (``KC-012`` → ``KC-013``, tự nới khi tràn: ``KC-099`` → ``KC-100``); không có số
	cuối thì thêm ``-01``, ``-02``…; bỏ qua mã đã có (kể cả dụng cụ đã Ngừng sử dụng); tối đa 1.000 lần thử.
	"""
	code = normalize_code(code)
	match = _TRAILING_DIGITS.match(code)
	if match:
		stem, digits = match.groups()
		start = int(digits) + 1
		candidates = (f"{stem}{str(n).zfill(len(digits))}" for n in range(start, start + SUGGEST_ATTEMPTS))
	else:
		stem = f"{code}-"
		candidates = (f"{stem}{n:02d}" for n in range(1, SUGGEST_ATTEMPTS + 1))
	taken = _codes_with_prefix(stem)
	for candidate in candidates:
		if len(candidate) > CODE_MAX_LENGTH:
			break
		if candidate not in taken:
			return candidate
	frappe.throw(
		_(
			"No free instrument code found after {0} attempts starting from {1}. Enter a different code."
		).format(SUGGEST_ATTEMPTS, code)
	)


def throw_duplicate(code: str):
	"""DuplicateEntryError có mã gợi ý (FR-M1-01.4, UC-01 E1)."""
	frappe.throw(
		_("Instrument Code {0} already exists. Next free code: {1}").format(code, suggest_code(code)),
		frappe.DuplicateEntryError,
		title=_("Duplicate Instrument Code"),
	)


def method_set(doc_or_rows) -> frozenset[str]:
	"""Tập phương pháp tương thích (bỏ dòng trống) của một Instrument, dict Instrument hoặc danh sách dòng."""
	if isinstance(doc_or_rows, Document | dict):
		rows = doc_or_rows.get("compatible_methods") or []
	else:
		rows = doc_or_rows or []
	methods = set()
	for row in rows:
		method = row if isinstance(row, str) else row.get("method")
		if method:
			methods.add(method)
	return frozenset(methods)


def families(methods: Iterable[str]) -> frozenset[str]:
	"""Họ phương pháp (``Steam``/``Plasma``/``EO``) của các phương pháp tương thích."""
	return frozenset(METHOD_FAMILY[method] for method in methods if method in METHOD_FAMILY)
