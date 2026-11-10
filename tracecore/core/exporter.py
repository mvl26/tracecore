"""Xuất báo cáo ra Excel/CSV theo hồ sơ ánh xạ cột `Report Export Profile` (FEAT-064; FR-M13-12, 12.1; BRU-RPT-002;
NFR-PRIV-01; UC-49 E3; A-147 Q1, j).

- Module đăng ký loại xuất qua hook ``tracecore_export_kinds`` (mỗi hàm trả list ``ExportKind``): khóa, nhãn, các cột
  có thể xuất, hàm lấy dòng theo bộ lọc, vai trò được xuất.
- Hồ sơ chọn cột và đặt tiêu đề theo mẫu cơ quan quản lý yêu cầu (OQ-V12-02), định dạng Excel/CSV, bảng mã, dấu phân
  cách, định dạng ngày. Không hồ sơ → mọi cột, tiêu đề dịch theo ngôn ngữ người dùng, Excel.
- Cột mã người bệnh dạng rõ hoặc họ tên không bao giờ được xuất: chặn khi lưu hồ sơ, khi đăng ký loại xuất và khi tạo
  file (``EXPORT_COLUMN_FORBIDDEN``). Loại xuất chỉ khai báo ``patient_code_masked``.
"""

import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime

from tracecore.core import extension
from tracecore.core.errors import Block, BlockedError

HOOK = "tracecore_export_kinds"
PROFILE_DOCTYPE = "Report Export Profile"
# trường không bao giờ được xuất (NFR-PRIV-01, FR-M13-12.1)
FORBIDDEN_FIELDS = frozenset(
	{
		"patient_code",
		"patient_code_hash",
		"patient_name",
		"full_name",
		"first_name",
		"last_name",
		"ho_ten",
		"ho_va_ten",
	}
)
DATE_FORMATS = {
	"dd/mm/yyyy": "%d/%m/%Y",
	"yyyy-mm-dd": "%Y-%m-%d",
	"mm/dd/yyyy": "%m/%d/%Y",
	"dd-mm-yyyy": "%d-%m-%Y",
	"dd.mm.yyyy": "%d.%m.%Y",
}
ENCODINGS = {"UTF-8": "utf-8-sig", "Windows-1258": "cp1258", "Windows-1252": "cp1252"}
DELIMITERS = {",": ",", ";": ";", "Tab": "\t"}
EXCEL_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_TYPE = "text/csv"


@dataclass
class ExportField:
	field: str
	label: str  # nhãn tiếng Anh, dịch theo ngôn ngữ người dùng làm tiêu đề mặc định
	kind: str = "text"  # text | int | float | date | check | select (giá trị dịch qua _())
	context: str | None = None  # context dịch giá trị select (vd DocType)


@dataclass
class ExportKind:
	key: str
	label: str
	fields: list[ExportField]
	rows: Callable[[dict], list[dict]]
	roles: Sequence[str] = ("TC R01", "TC R11", "System Manager")
	filters: Sequence[str] = field(default_factory=lambda: ("period_from", "period_to"))


def _forbidden(name) -> bool:
	return (name or "").strip().lower() in FORBIDDEN_FIELDS


def forbidden_block(name):
	return BlockedError(
		Block(
			"EXPORT_COLUMN_FORBIDDEN",
			_("Column not allowed"),
			_("Column {0} would put a patient name or a clear patient code in the file.").format(name),
			_("Remove the column; files only carry the masked patient code."),
			items=["columns"],
		)
	)


def kinds() -> dict[str, ExportKind]:
	out: dict[str, ExportKind] = {}
	for result in extension.run(HOOK):
		for kind in result or []:
			out[kind.key] = kind
	return out


def get_kind(key) -> ExportKind:
	kind = kinds().get(key or "")
	if not kind:
		frappe.throw(_("Unknown report type {0}.").format(key))
	for item in kind.fields:
		if _forbidden(item.field):
			raise forbidden_block(item.field)
	return kind


def validate_profile(doc):
	"""``ReportExportProfile.validate``: loại xuất có thật, cột thuộc loại, không trùng, không cột bị cấm (E3)."""
	doc.profile_name = " ".join((doc.profile_name or "").split())
	kind = kinds().get(doc.export_kind or "")
	if not kind:
		frappe.throw(_("Unknown report type {0}.").format(doc.export_kind))
	fields = {item.field for item in kind.fields}
	sources, headers = set(), set()
	for row in doc.columns or []:
		row.source_field = (row.source_field or "").strip()
		row.header = " ".join((row.header or "").split())
		if _forbidden(row.source_field):
			raise forbidden_block(row.source_field)
		if row.source_field not in fields:
			frappe.throw(
				_("Row {0}: {1} is not a column of report type {2}.").format(
					row.idx, row.source_field, _(kind.label)
				)
			)
		if row.source_field in sources:
			frappe.throw(_("Row {0}: column {1} is mapped twice.").format(row.idx, row.source_field))
		if row.header.casefold() in headers:
			frappe.throw(_("Row {0}: header {1} is listed twice.").format(row.idx, row.header))
		sources.add(row.source_field)
		headers.add(row.header.casefold())


def _profile(name, kind):
	if not name:
		return None
	doc = frappe.get_doc(PROFILE_DOCTYPE, name)
	if doc.export_kind != kind.key:
		frappe.throw(_("Profile {0} is for another report type.").format(name))
	return doc


def columns(kind, profile=None):
	"""[(ExportField, tiêu đề)] theo hồ sơ (thứ tự hồ sơ) hoặc mặc định (mọi cột)."""
	by_field = {item.field: item for item in kind.fields}
	if not profile:
		return [(item, _(item.label)) for item in kind.fields]
	out = []
	for row in profile.columns:
		if _forbidden(row.source_field):
			raise forbidden_block(row.source_field)
		if row.source_field in by_field:
			out.append((by_field[row.source_field], row.header))
	return out


def _value(item, value, date_format):
	if value is None or value == "":
		return ""
	if item.kind == "date":
		return getdate(value).strftime(date_format)
	if item.kind == "int":
		return cint(value)
	if item.kind == "float":
		return flt(value)
	if item.kind == "check":
		return _("Yes") if cint(value) else _("No")
	if item.kind == "select":
		return _(str(value), context=item.context)
	return str(value)


def _require_role(kind):
	if frappe.session.user == "Administrator":
		return
	if not set(frappe.get_roles()) & set(kind.roles):
		raise frappe.PermissionError(_("You are not allowed to export {0}.").format(_(kind.label)))


def build(key, filters=None, profile=None):
	"""(tên file, nội dung bytes, content type) của loại xuất ``key`` theo bộ lọc và hồ sơ."""
	kind = get_kind(key)
	_require_role(kind)
	doc = _profile(profile, kind)
	cols = columns(kind, doc)
	date_format = DATE_FORMATS.get((doc.date_format if doc else None) or "dd/mm/yyyy", "%d/%m/%Y")
	header = [title for _item, title in cols]
	data = [
		[_value(item, row.get(item.field), date_format) for item, _title in cols]
		for row in kind.rows(filters or {})
	]
	stem = f"{frappe.scrub(kind.key)}-{now_datetime().strftime('%Y%m%d-%H%M')}"
	if doc and doc.file_format == "CSV":
		out = io.StringIO()
		writer = csv.writer(out, delimiter=DELIMITERS.get(doc.delimiter or ",", ","), lineterminator="\r\n")
		writer.writerow(header)
		writer.writerows([["" if value == "" else str(value) for value in line] for line in data])
		encoding = ENCODINGS.get(doc.encoding or "UTF-8", "utf-8-sig")
		return f"{stem}.csv", out.getvalue().encode(encoding, errors="replace"), CSV_TYPE
	from frappe.utils.xlsxutils import make_xlsx

	sheet = (_(kind.label) or "Data")[:31]
	content = make_xlsx([header, *data], sheet).getvalue()
	return f"{stem}.xlsx", content, EXCEL_TYPE


def profiles(key):
	"""Hồ sơ của một loại xuất (tên, định dạng, mô tả)."""
	return frappe.get_all(
		PROFILE_DOCTYPE,
		filters={"export_kind": key},
		fields=["name", "file_format", "description"],
		order_by="name asc",
	)
