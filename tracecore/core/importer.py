"""Khung import danh mục ban đầu từ Excel mẫu (FEAT-011, FR-M9-11, EI-SW-007, UC-39; A-41).

Không biết gì về nghiệp vụ: mỗi module khai báo "loại import" (`ImportKind`: cột, mã, kiểm, ghi) và trả chúng qua hook
``tracecore_import_kinds`` (luật R1: core không import M1-M10). Khung lo phần chung:

- mẫu ``.xlsx`` sinh từ khai báo cột (sheet dữ liệu + sheet hướng dẫn);
- đọc file theo TÊN cột (mã cột, nhãn tiếng Anh hoặc nhãn đã dịch, có/không dấu ``*``), chuẩn hóa ô (số, ngày Excel
  hoặc ``dd/mm/yyyy``, có/không, giá trị chọn, danh sách); cột mã hệ thống (Set ID, TB-, NV-…) → từ chối cả file
  (BRU-ID-006, UC-39 E2);
- gom dòng thành "đơn vị" (một dòng, hoặc nhóm dòng cùng mã khi `group_by`; phần đầu mâu thuẫn → ``GROUP_CONFLICT``);
- "Kiểm tra" không ghi gì; "Ghi sổ" ghi từng đơn vị trong savepoint riêng, mã đã có thì bỏ qua (A-41 Q3), đơn vị lỗi
  hoàn tác riêng; kết quả từng dòng lưu ở `Import Batch`. File lớn (> `BACKGROUND_ROWS` dòng) chạy nền hàng ``long``.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from io import BytesIO

import frappe
from frappe import _
from frappe.utils import now_datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from tracecore.core.errors import BlockedError

HOOK = "tracecore_import_kinds"
MAX_ROWS = 5000
MAX_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # chặn zip bomb: .xlsx là zip
MAX_SCAN_ROWS = 20_000
BACKGROUND_ROWS = 200
DATE_FORMAT = "dd/mm/yyyy"
SAVEPOINT = "tc_import_unit"
# so khớp sau khi bỏ dấu (`_plain`): "có" / "không" người dùng gõ cũng được nhận
TRUE_WORDS = {"1", "x", "yes", "y", "true", "co", "c"}
FALSE_WORDS = {"0", "no", "n", "false", "khong", "k"}
DATA_SHEET = "Data"
GUIDE_SHEET = "Guide"


class ImportFileError(Exception):
	"""File không đọc được / sai mẫu / vượt giới hạn (``IMPORT_FILE_INVALID``); ``reason`` đã qua ``_()``."""

	def __init__(self, reason: str):
		super().__init__(reason)
		self.reason = reason


@dataclass
class Column:
	field: str
	label: str  # nhãn tiếng Anh (nguồn bản dịch); tiêu đề mẫu dùng bản dịch theo ngôn ngữ người dùng
	required: bool = False
	kind: str = "text"  # text | int | float | date | check | select | list
	options: Sequence[str] = ()
	help: str = ""


@dataclass
class Issue:
	row: int  # số dòng Excel (tiêu đề = 1)
	code: str
	field: str | None
	reason: str


@dataclass
class ParsedRow:
	row: int
	values: dict


class RowError(Exception):
	"""`write` của loại import ném khi đơn vị không ghi được, kèm lỗi theo dòng."""

	def __init__(self, issues: list[Issue]):
		super().__init__("; ".join(issue.reason for issue in issues))
		self.issues = issues


@dataclass
class ImportKind:
	key: str
	label: str
	doctype: str
	columns: list[Column]
	code_field: str
	exists: Callable[[str], bool]
	validate: Callable[[list[ParsedRow]], list[Issue]]
	write: Callable[[list[ParsedRow]], str | None]
	group_by: str | None = None
	group_fields: Sequence[str] = ()  # trường phần đầu của nhóm: dòng sau để trống hoặc trùng dòng đầu
	forbidden_columns: Sequence[str] = ()  # tiêu đề cột mã hệ thống (BRU-ID-006)
	roles: Sequence[str] = ("TC R10", "TC R02", "System Manager")
	code_of: Callable[[dict], str] | None = None  # mã "đã có" tính từ nhiều cột (vd thẻ hoặc email nhân viên)
	guide: Sequence[str] = field(default_factory=tuple)  # câu hướng dẫn thêm cho sheet Guide


# --- Đăng ký loại import -------------------------------------------------------------------------------------------


def kinds() -> dict[str, ImportKind]:
	"""Mọi loại import do các module khai báo qua hook ``tracecore_import_kinds`` (mỗi hàm trả list ImportKind)."""
	out: dict[str, ImportKind] = {}
	for path in frappe.get_hooks(HOOK) or []:
		for kind in frappe.get_attr(path)():
			out[kind.key] = kind
	return out


def get_kind(key: str) -> ImportKind:
	kind = kinds().get(key)
	if not kind:
		raise ImportFileError(_("Unknown import type {0}.").format(key))
	return kind


def department_ref(value) -> str | None:
	"""Tên Department theo tên đầy đủ (``Khoa A - TC``) hoặc tên khoa người dùng gõ; không có → None.

	Dùng chung cho các loại import có cột khoa (ERPNext Department là danh mục dùng chung, không thuộc module nào).
	"""
	if not value:
		return None
	if frappe.db.exists("Department", value):
		return value
	return frappe.db.get_value("Department", {"department_name": value}, "name")


# --- Mẫu Excel -----------------------------------------------------------------------------------------------------


def _header(column: Column) -> str:
	return _(column.label) + (" *" if column.required else "")


def _kind_text(column: Column) -> str:
	return {
		"text": _("Text"),
		"int": _("Whole number"),
		"float": _("Number"),
		"date": _("Date cell or text dd/mm/yyyy"),
		"check": _("Yes / No (1, x, Yes or 0, No)"),
		"select": _("One of: {0}"),
		"list": _("Several of: {0}, separated by commas"),
	}[column.kind].format(", ".join(column.options))


def build_template(key: str) -> bytes:
	"""File mẫu ``.xlsx``: sheet dữ liệu (tiêu đề in đậm, cột bắt buộc có ``*``) và sheet hướng dẫn cột."""
	kind = get_kind(key)
	book = Workbook()
	sheet = book.active
	sheet.title = DATA_SHEET
	sheet.append([_header(column) for column in kind.columns])
	bold = Font(bold=True)
	for index, cell in enumerate(sheet[1]):
		cell.font = bold
		sheet.column_dimensions[cell.column_letter].width = 26
		if kind.columns[index].kind == "date":
			for row in range(2, 1002):
				sheet.cell(row=row, column=index + 1).number_format = DATE_FORMAT
	sheet.freeze_panes = "A2"

	guide = book.create_sheet(GUIDE_SHEET)
	guide.append([_("Excel column"), _("Requirement"), _("Values"), _("Description")])
	for cell in guide[1]:
		cell.font = bold
	for column in kind.columns:
		guide.append(
			[
				_(column.label),
				_("Required") if column.required else _("Optional"),
				_kind_text(column),
				_(column.help) if column.help else "",
			]
		)
	guide.append([])
	for rule in (
		_("Fill in the first sheet from row 2; row 1 is the header. Columns are matched by name."),
		_("At most {0} rows and {1} MB per file.").format(MAX_ROWS, MAX_BYTES // (1024 * 1024)),
		_("Rows whose code already exists are skipped; change existing records on the Desk."),
		_("Wrong rows are listed with their row number; correct rows are saved when you confirm."),
		*[_(text) for text in kind.guide],
	):
		guide.append([rule])
	for letter, width in zip("ABCD", (30, 16, 44, 80), strict=True):
		guide.column_dimensions[letter].width = width
	buffer = BytesIO()
	book.save(buffer)
	return buffer.getvalue()


# --- Đọc file ------------------------------------------------------------------------------------------------------


def _file_error(reason: str) -> ImportFileError:
	return ImportFileError(reason + " " + _("Download the template, fill it in and upload it again."))


def _norm(value) -> str:
	return " ".join(str(value).replace("*", " ").split()).casefold() if value is not None else ""


def _text(value) -> str:
	if value is None:
		return ""
	if isinstance(value, float) and value.is_integer():
		return str(int(value))
	if isinstance(value, datetime | date):
		return value.strftime("%d/%m/%Y")
	return " ".join(str(value).split())


def _check_container(content: bytes) -> None:
	if not content:
		raise _file_error(_("The file is empty."))
	if len(content) > MAX_BYTES:
		raise _file_error(_("The file is larger than {0} MB.").format(MAX_BYTES // (1024 * 1024)))
	try:
		with zipfile.ZipFile(BytesIO(content)) as archive:
			total = sum(info.file_size for info in archive.infolist())
			names = set(archive.namelist())
	except zipfile.BadZipFile:
		raise _file_error(_("The file is not an Excel .xlsx workbook.")) from None
	if "xl/workbook.xml" not in names:
		raise _file_error(_("The file is not an Excel .xlsx workbook."))
	if total > MAX_UNCOMPRESSED_BYTES:
		raise _file_error(_("The workbook is too large to read."))


def _aliases(kind: ImportKind) -> dict[str, str]:
	aliases: dict[str, str] = {}
	for column in kind.columns:
		for text in (column.field, column.label, _(column.label)):
			aliases.setdefault(_norm(text), column.field)
	return aliases


def _number(value):
	if value is None or (isinstance(value, str) and not value.strip()):
		return None, True
	if isinstance(value, bool):
		return None, False
	if isinstance(value, int | float):
		number = float(value)
	elif isinstance(value, str):
		try:
			number = float(value.strip().replace(",", "."))
		except ValueError:
			return None, False
	else:
		return None, False
	return (number, True) if math.isfinite(number) else (None, False)


def _date(value):
	if value is None or (isinstance(value, str) and not value.strip()):
		return None, True
	if isinstance(value, datetime):
		return value.date(), True
	if isinstance(value, date):
		return value, True
	if isinstance(value, str):
		for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
			try:
				return datetime.strptime(value.strip(), pattern).date(), True
			except ValueError:
				continue
	return None, False


def _plain(text: str) -> str:
	"""Chữ thường, bỏ dấu tiếng Việt để so khớp từ có/không."""
	folded = unicodedata.normalize("NFD", text.casefold().replace(chr(0x111), "d"))  # chữ đ không tách dấu
	return "".join(char for char in folded if not unicodedata.combining(char))


def _option(column: Column, text: str):
	for option in column.options:
		if option.casefold() == text.casefold() or _(option).casefold() == text.casefold():
			return option
	return None


def _cell(column: Column, value, row: int) -> tuple[object, Issue | None]:
	"""Giá trị đã chuẩn hóa của một ô theo kiểu cột, hoặc lỗi dòng."""

	def bad(reason):
		return None, Issue(row, "VALUE_INVALID", column.field, reason)

	shown = _text(value)[:40]
	if column.kind in ("int", "float"):
		number, ok = _number(value)
		if not ok or (column.kind == "int" and number is not None and not number.is_integer()):
			return bad(_('{0}: "{1}" is not a valid number.').format(_(column.label), shown))
		return (int(number) if column.kind == "int" and number is not None else number), None
	if column.kind == "date":
		day, ok = _date(value)
		return (
			(day, None)
			if ok
			else bad(_('{0}: "{1}" is not a date dd/mm/yyyy.').format(_(column.label), shown))
		)
	text = _text(value)
	if column.kind == "check":
		if not text:
			return None, None
		if _plain(text) in TRUE_WORDS:
			return True, None
		if _plain(text) in FALSE_WORDS:
			return False, None
		return bad(_('{0}: "{1}" must be Yes or No.').format(_(column.label), shown))
	if column.kind == "select":
		if not text:
			return None, None
		option = _option(column, text)
		if option is None:
			return bad(
				_('{0}: "{1}" is not one of {2}.').format(_(column.label), shown, ", ".join(column.options))
			)
		return option, None
	if column.kind == "list":
		parts = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
		values = []
		for part in parts:
			option = _option(column, part) if column.options else part
			if option is None:
				return bad(
					_('{0}: "{1}" is not one of {2}.').format(
						_(column.label), part[:40], ", ".join(column.options)
					)
				)
			values.append(option)
		return values, None
	return text or None, None


def parse(kind: ImportKind, content: bytes) -> tuple[list[ParsedRow], list[Issue]]:
	"""Đọc sheet đầu: trả các dòng dữ liệu (bỏ dòng trống) với số dòng Excel và lỗi giá trị ô.

	Ném ``ImportFileError`` khi file rỗng / không phải .xlsx / quá cỡ / quá ``MAX_ROWS`` dòng / thiếu cột bắt buộc /
	có cột mã hệ thống. Ô công thức lấy giá trị đã lưu.
	"""
	_check_container(content)
	try:
		book = load_workbook(BytesIO(content), read_only=True, data_only=True)
	except Exception:
		raise _file_error(_("The file is not an Excel .xlsx workbook.")) from None
	try:
		return _read(kind, book)
	except ImportFileError:
		raise
	except Exception:
		raise _file_error(_("The workbook could not be read.")) from None
	finally:
		book.close()


def _read(kind: ImportKind, book) -> tuple[list[ParsedRow], list[Issue]]:
	if not book.worksheets:
		raise _file_error(_("The workbook has no sheet."))
	iterator = book.worksheets[0].iter_rows(values_only=True)
	header = next(iterator, None)
	if not header or all(_text(cell) == "" for cell in header):
		raise _file_error(_("Row 1 of the first sheet must be the header row."))
	forbidden = {_norm(text): text for text in kind.forbidden_columns}
	found = [forbidden[_norm(cell)] for cell in header if _norm(cell) in forbidden]
	if found:
		raise _file_error(
			_("Column(s) {0} hold codes the system generates; remove them from the file.").format(
				", ".join(found)
			)
		)
	aliases = _aliases(kind)
	columns: dict[str, int] = {}
	for index, cell in enumerate(header):
		name = aliases.get(_norm(cell))
		if name:
			columns.setdefault(name, index)
	missing = [column for column in kind.columns if column.required and column.field not in columns]
	if missing:
		raise _file_error(
			_("Missing column(s): {0}.").format(", ".join(_(column.label) for column in missing))
		)
	by_field = {column.field: column for column in kind.columns}
	rows: list[ParsedRow] = []
	issues: list[Issue] = []
	for number, values in enumerate(iterator, start=2):
		if number > MAX_SCAN_ROWS:
			raise _file_error(_("The sheet has too many rows to read."))
		if all(_text(cell) == "" for cell in values):
			continue
		if len(rows) >= MAX_ROWS:
			raise _file_error(_("The file has more than {0} data rows.").format(MAX_ROWS))
		parsed = {}
		for name, index in columns.items():
			value, issue = _cell(by_field[name], values[index] if index < len(values) else None, number)
			parsed[name] = value
			if issue:
				issues.append(issue)
		rows.append(ParsedRow(number, parsed))
	return rows, issues


# --- Gom dòng, kiểm -------------------------------------------------------------------------------------------------


def _required_issues(kind: ImportKind, row: ParsedRow, head: bool) -> list[Issue]:
	issues = []
	for column in kind.columns:
		if not column.required or row.values.get(column.field) not in (None, "", []):
			continue
		if not head and column.field in kind.group_fields:
			continue  # phần đầu của nhóm chỉ bắt buộc ở dòng đầu
		issues.append(Issue(row.row, "REQUIRED", column.field, _("{0} is required.").format(_(column.label))))
	return issues


def _units(kind: ImportKind, rows: list[ParsedRow]) -> tuple[list[list[ParsedRow]], list[Issue]]:
	if not kind.group_by:
		return [[row] for row in rows], []
	groups: dict[str, list[ParsedRow]] = {}
	issues: list[Issue] = []
	for row in rows:
		key = (
			(row.values.get(kind.group_by) or "").casefold()
			if isinstance(row.values.get(kind.group_by), str)
			else ""
		)
		groups.setdefault(key or f"__row{row.row}", []).append(row)
	for unit in groups.values():
		head = unit[0].values
		for row in unit[1:]:
			for name in kind.group_fields:
				value = row.values.get(name)
				if value not in (None, "", []) and value != head.get(name):
					issues.append(
						Issue(
							row.row,
							"GROUP_CONFLICT",
							name,
							_("{0} differs from the first row of {1} (row {2}).").format(
								_(next(c.label for c in kind.columns if c.field == name)),
								head.get(kind.group_by),
								unit[0].row,
							),
						)
					)
	return list(groups.values()), issues


def _code(kind: ImportKind, unit: list[ParsedRow]) -> str:
	if kind.code_of:
		return kind.code_of(unit[0].values) or ""
	return unit[0].values.get(kind.code_field) or ""


def _analyse(kind: ImportKind, content: bytes):
	"""(đơn vị, lỗi theo đơn vị {id(unit): [Issue]}, mã đã có, tổng số dòng)."""
	rows, issues = parse(kind, content)
	units, group_issues = _units(kind, rows)
	issues += group_issues
	reported = {(issue.row, issue.field) for issue in issues}  # ô sai giá trị không báo thêm "bắt buộc"
	for unit in units:
		for index, row in enumerate(unit):
			issues += [
				issue
				for issue in _required_issues(kind, row, head=index == 0)
				if (issue.row, issue.field) not in reported
			]
	rows_with_issue = {issue.row for issue in issues}
	per_unit: dict[int, list[Issue]] = {}
	existing: list[str] = []
	for unit in units:
		own = [issue for issue in issues if issue.row in {row.row for row in unit}]
		code = _code(kind, unit)
		if not own and code and kind.exists(code):
			existing.append(code)
			continue
		if not own:
			own = kind.validate(unit)
		per_unit[id(unit)] = own
	return units, per_unit, existing, len(rows), rows_with_issue


def content_hash(content: bytes) -> str:
	return hashlib.sha256(content).hexdigest()


def previous_batch(key: str, content: bytes) -> str | None:
	"""Import Batch gần nhất (chưa thất bại) của đúng file này: loại không có "đã có" (vd Set Unit) sẽ ghi lại lần hai."""
	names = frappe.get_all(
		"Import Batch",
		filters={"kind": key, "content_hash": content_hash(content), "status": ["!=", "Failed"]},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	return names[0] if names else None


def check(key: str, content: bytes) -> dict:
	"""Kiểm file, không ghi gì: ``{"total", "units", "valid", "existing": [mã], "issues": [Issue dict],
	"previous_batch"}`` (`previous_batch`: file y hệt đã được ghi sổ trước đó)."""
	kind = get_kind(key)
	units, per_unit, existing, total, _rows = _analyse(kind, content)
	issues = sorted(
		(i for own in per_unit.values() for i in own), key=lambda issue: (issue.row, issue.field or "")
	)
	valid = sum(1 for unit in units if id(unit) in per_unit and not per_unit[id(unit)])
	return {
		"total": total,
		"units": len(units),
		"valid": valid,
		"existing": existing,
		"issues": [asdict(issue) for issue in issues],
		"previous_batch": previous_batch(key, content),
	}


# --- Ghi sổ ------------------------------------------------------------------------------------------------------


def run(key: str, content: bytes, file_url: str | None) -> str:
	"""Tạo `Import Batch` và ghi các đơn vị hợp lệ; > ``BACKGROUND_ROWS`` dòng thì chạy nền. Trả tên Import Batch."""
	kind = get_kind(key)
	rows, _issues = parse(kind, content)  # file sai mẫu → lỗi ngay, không tạo batch
	batch = frappe.get_doc(
		{
			"doctype": "Import Batch",
			"kind": key,
			"file": file_url,
			"content_hash": content_hash(content),
			"status": "Queued",
			"total": len(rows),
		}
	)
	batch.flags.tc_import = True
	batch.insert(ignore_permissions=True)
	if len(rows) > BACKGROUND_ROWS:
		frappe.enqueue(
			"tracecore.core.importer.execute_batch",
			queue="long",
			timeout=3600,
			enqueue_after_commit=True,
			batch=batch.name,
			content=content,
		)
	else:
		execute_batch(batch.name, content)
	return batch.name


def _file_content(file_url: str) -> bytes:
	return frappe.get_doc("File", {"file_url": file_url}).get_content()


def execute_batch(batch: str, content: bytes | None = None) -> None:
	"""Ghi từng đơn vị của file vào DB; mỗi đơn vị một savepoint; cập nhật kết quả vào `Import Batch`."""
	doc = frappe.get_doc("Import Batch", batch)
	kind = get_kind(doc.kind)
	_save(doc, status="Running", started_at=now_datetime())
	try:
		units, per_unit, existing, _total, _rows = _analyse(kind, content or _file_content(doc.file))
		results = []
		for unit in units:
			results += _write_unit(kind, unit, per_unit.get(id(unit)), existing)
	except Exception as error:
		# lỗi ngoài dự kiến (file đổi, lỗi máy chủ): bỏ mọi ghi dở, đánh dấu Failed nếu batch đã được lưu từ trước
		frappe.db.rollback()
		if frappe.db.exists("Import Batch", batch):
			frappe.db.set_value(
				"Import Batch",
				batch,
				{"status": "Failed", "finished_at": now_datetime(), "error": str(error)[:500]},
				update_modified=False,
			)
			frappe.db.commit()  # nosemgrep: job nền cần giữ trạng thái Failed dù ném lỗi
		raise
	doc.set("rows", [])
	for row in results:
		doc.append("rows", row)
	_save(
		doc,
		status="Done",
		finished_at=now_datetime(),
		created=sum(1 for row in results if row["result"] == "Created"),
		skipped=sum(1 for row in results if row["result"] == "Existing"),
		failed=sum(1 for row in results if row["result"] == "Error"),
	)


def _write_unit(kind: ImportKind, unit, issues, existing) -> list[dict]:
	code = _code(kind, unit)
	if issues is None and code in existing:
		return [{"row_no": unit[0].row, "code": code, "result": "Existing", "ref_doctype": kind.doctype}]
	if issues:
		return [_error_row(issue, code) for issue in issues]
	frappe.db.savepoint(SAVEPOINT)
	try:
		name = kind.write(unit)
	except RowError as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		return [_error_row(issue, code) for issue in error.issues]
	except (BlockedError, frappe.ValidationError, frappe.DoesNotExistError) as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.clear_last_message()
		if isinstance(error, BlockedError):
			issue = Issue(unit[0].row, error.block.code, None, error.block.reason)
		else:
			issue = Issue(unit[0].row, "WRITE_FAILED", None, frappe.utils.strip_html(str(error)))
		return [_error_row(issue, code)]
	return [
		{
			"row_no": unit[0].row,
			"code": code,
			"result": "Created",
			"ref_doctype": kind.doctype,
			"ref_name": name,
		}
	]


def _error_row(issue: Issue, code: str) -> dict:
	return {
		"row_no": issue.row,
		"code": code,
		"result": "Error",
		"field": issue.field,
		"error_code": issue.code,
		"message": issue.reason[:500],
	}


def _save(doc, **values) -> None:
	doc.update(values)
	doc.flags.tc_import = True
	doc.save(ignore_permissions=True)
