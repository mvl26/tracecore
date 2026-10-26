"""Nguồn chuẩn và bộ sinh quyền RBAC TraceCore (FEAT-003, SEC #13)."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import frappe

ROLE_CODES = tuple(f"R{i:02d}" for i in range(1, 11))
ROLE_NAMES = {code: f"TC {code}" for code in ROLE_CODES}
MATRIX_PATH = Path(__file__).parents[1] / "fixtures" / "permission_matrix.csv"
FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "custom_docperm.json"
VALID_SYMBOLS = frozenset("RWSA")

# DocType do một amendment mới hơn ma trận BA #13 quản lý bằng đường riêng; không sinh Custom DocPerm ở đây để
# hai nguồn không ghi đè nhau. Custom DocPerm thay thế toàn bộ quyền chuẩn của DocType, nên Item/Stock Entry của
# ERPNext phải để ``inventory.permissions.ensure_permissions`` (FEAT-041, A-07 V11) tự sao chép quyền chuẩn
# trước rồi chỉnh theo V11.
AMENDED_ELSEWHERE = frozenset({"Item", "Stock Entry"})

# Set Unit chỉ tạo qua Cấp Set ID (``set_units.issue_batch``; FEAT-016, A-13 G4) và Recall Order chỉ lập qua dịch vụ
# thu hồi (FEAT-029 R2): ký hiệu W của ma trận vẫn cho ghi nhưng không sinh cờ ``create``, để Desk không có nút
# "Thêm" cho vai trò nào.
NO_CREATE_DOCTYPES = frozenset({"Set Unit", "Recall Order"})

# Quyền thêm theo amendment cho vai trò ngoài R01-R10 (ký hiệu SEC như ma trận, không bao giờ có delete):
# Instrument: System Manager đọc/ghi (FEAT-014, A-06 I15).
AMENDMENT_GRANTS: dict[str, dict[str, str]] = {
	"Instrument": {"System Manager": "RW"},
	# FEAT-015 A-09 S12: System Manager đọc/tạo/ghi loại bộ; Set BOM Item chỉ đọc (dòng bất biến, chỉ bom_versions ghi)
	"Instrument Set Type": {"System Manager": "RW"},
	"Set BOM Item": {"System Manager": "R"},
	# FEAT-016 A-13 G4: System Manager đọc/ghi Set Unit (cờ create bị bỏ ở NO_CREATE_DOCTYPES)
	"Set Unit": {"System Manager": "RW"},
}


@dataclass(frozen=True)
class PermissionRow:
	code: str
	doctype: str
	permissions: dict[str, str]
	notes: str = ""


class PermissionMatrix(list[PermissionRow]):
	roles = ROLE_CODES


def _normalize_symbols(value: str) -> str:
	value = "".join(dict.fromkeys((value or "").replace(" ", "").upper()))
	invalid = set(value) - VALID_SYMBOLS
	if invalid:
		raise ValueError(f"Invalid permission symbols: {''.join(sorted(invalid))}")
	return "".join(symbol for symbol in "RWSA" if symbol in value)


def load_permission_matrix(path: str | Path = MATRIX_PATH) -> PermissionMatrix:
	rows = PermissionMatrix()
	seen_codes: set[str] = set()
	seen_doctypes: set[str] = set()
	with Path(path).open(encoding="utf-8", newline="") as handle:
		reader = csv.DictReader(handle)
		expected = ["code", "doctype", *ROLE_CODES, "notes"]
		if reader.fieldnames != expected:
			raise ValueError(f"Permission matrix columns must be: {', '.join(expected)}")
		for raw in reader:
			code = raw["code"].strip()
			doctype = raw["doctype"].strip()
			if not code or not doctype or code in seen_codes or doctype in seen_doctypes:
				raise ValueError(f"Duplicate or empty permission row: {code}/{doctype}")
			seen_codes.add(code)
			seen_doctypes.add(doctype)
			rows.append(
				PermissionRow(
					code=code,
					doctype=doctype,
					permissions={role: _normalize_symbols(raw[role]) for role in ROLE_CODES},
					notes=raw["notes"].strip(),
				)
			)
	return rows


def permission_flags(symbols: str) -> dict[str, int]:
	"""Map SEC R/W/S/A sang cờ Frappe; không bao giờ cấp delete."""

	symbols = _normalize_symbols(symbols)
	flags: dict[str, int] = {}
	if "R" in symbols:
		flags.update(read=1, report=1, print=1, export=1)
	if "W" in symbols:
		flags.update(write=1, create=1)
	if "S" in symbols:
		flags["submit"] = 1
	if "A" in symbols:
		flags.update(cancel=1, amend=1)
	return flags


def flags_for(doctype: str, symbols: str) -> dict[str, int]:
	"""Cờ Frappe của ký hiệu SEC; DocType trong ``NO_CREATE_DOCTYPES`` không bao giờ nhận cờ ``create``."""
	flags = permission_flags(symbols)
	if doctype in NO_CREATE_DOCTYPES:
		flags.pop("create", None)
	return flags


def build_custom_docperms(existing_doctypes: set[str] | None = None) -> list[dict]:
	"""Sinh fixture cho DocType đã tồn tại; các dòng future vẫn ở CSV để CI theo dõi."""

	if existing_doctypes is None:
		existing_doctypes = set(frappe.get_all("DocType", pluck="name"))
	records = []
	for row in load_permission_matrix():
		if row.doctype not in existing_doctypes or row.doctype in AMENDED_ELSEWHERE:
			continue
		for code in ROLE_CODES:
			flags = flags_for(row.doctype, row.permissions[code])
			if not flags:
				continue
			name = hashlib.sha256(f"{row.doctype}:{ROLE_NAMES[code]}:0".encode()).hexdigest()[:10]
			records.append(
				{
					"doctype": "Custom DocPerm",
					"name": name,
					"parent": row.doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": ROLE_NAMES[code],
					"permlevel": 0,
					**flags,
				}
			)
		for role, symbols in AMENDMENT_GRANTS.get(row.doctype, {}).items():
			name = hashlib.sha256(f"{row.doctype}:{role}:0".encode()).hexdigest()[:10]
			records.append(
				{
					"doctype": "Custom DocPerm",
					"name": name,
					"parent": row.doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": role,
					"permlevel": 0,
					**flags_for(row.doctype, symbols),
				}
			)
	return records


def write_fixture(path: str | Path = FIXTURE_PATH) -> None:
	Path(path).write_text(
		json.dumps(build_custom_docperms(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
		encoding="utf-8",
	)
