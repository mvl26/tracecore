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
from frappe.utils import cint, today

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


def ordered_methods(methods: Iterable[str]) -> list[str]:
	"""Phương pháp theo thứ tự danh mục ``METHODS`` (phương pháp lạ, nếu có, xếp sau theo tên)."""
	methods = set(methods)
	known = [method for method in METHODS if method in methods]
	return known + sorted(methods.difference(METHODS))


def _current_methods(instrument: str) -> frozenset[str]:
	return frozenset(
		frappe.get_all(
			"Instrument Compatible Method",
			filters={"parent": instrument, "parenttype": "Instrument", "parentfield": "compatible_methods"},
			pluck="method",
		)
	)


def bom_usage(instrument: str) -> list[dict]:
	"""Loại bộ có BOM **hiện hành** chứa dụng cụ (A-06 I3, I13), sắp theo mã loại bộ.

	Mỗi dòng: ``{set_type, set_type_name, method, bom_version, compatible}``; ``compatible`` = họ phương pháp của
	loại bộ nằm trong họ phương pháp tương thích hiện tại của dụng cụ (loại bộ chưa khai phương pháp coi như
	tương thích). Phiên bản BOM cũ không tính. Đọc Set BOM Item/Instrument Set Type (cùng M1), chỉ đọc.
	"""
	rows = frappe.db.sql(
		"""
		select distinct st.name as set_type, st.set_type_name, st.method, st.current_bom_version as bom_version
		from `tabInstrument Set Type` st
		join `tabSet BOM Item` line
			on line.set_type = st.name and line.bom_version = st.current_bom_version
		where line.instrument = %s
		order by st.name
		""",
		(instrument,),
		as_dict=True,
	)
	if not rows:
		return []
	usable = families(_current_methods(instrument))
	return [
		{
			"set_type": row.set_type,
			"set_type_name": row.set_type_name,
			"method": row.method,
			"bom_version": cint(row.bom_version),
			"compatible": not row.method or row.method in usable,
		}
		for row in rows
	]


def retire(instrument: str, reason: str, confirm: bool = False) -> dict:
	"""Ngừng sử dụng dụng cụ (UC-01 E3, A-06 I13); một chiều, bắt buộc lý do.

	Dụng cụ còn trong BOM hiện hành mà chưa ``confirm`` → ``{"retired": False, "boms": [...]}``, không ghi gì;
	xong → ``{"retired": True, "boms": [...]}`` (Audit Log Update qua doc_events). Đã ngừng → ValidationError.
	"""
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is required to retire an instrument."))
	doc = frappe.get_doc("Instrument", instrument, for_update=True)
	if doc.status == "Retired":
		frappe.throw(_("Instrument {0} is already retired.").format(doc.name))
	boms = bom_usage(doc.name)
	if boms and not cint(confirm):
		return {"retired": False, "boms": boms}
	doc.status = "Retired"
	doc.retired_on = today()
	doc.retired_reason = reason
	doc.flags.tc_instrument = True
	doc.save()
	return {"retired": True, "boms": boms}
