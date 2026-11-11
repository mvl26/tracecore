"""Phần của gói hồ sơ KSNK cho đoàn kiểm tra (FEAT-074; FR-M9-30, FR-M9-30.1; BRU-RPT-002; NFR-PRIV-01; UC-57 bước 8,
E5; A-152).

- Mỗi module M9, M11-M16 đóng góp phần của mình qua hook ``tracecore_ic_dossier_sections`` (ADR-001): hàm trả list
  ``DossierSection`` — khóa, nhãn, thứ tự, các cột (``exporter.ExportField``), hàm lấy dòng theo ngữ cảnh kỳ, có in vào PDF
  hay chỉ ở Excel. M9 (`admin_reports.ic_dossier`) gom lại, không import module nghiệp vụ.
- Gói không bao giờ chứa dữ liệu cá nhân dạng rõ (FR-M9-30.1): cột tên người bệnh, mã BN rõ, tên nhân viên phơi nhiễm bị
  chặn khi đăng ký; cột ``*_masked`` chỉ nhận giá trị đã che (``***`` + tối đa 4 ký tự). Vi phạm → ``DossierPrivacyError``.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import get_last_day, getdate

from tracecore.core import exporter, extension
from tracecore.core.exporter import ExportField

HOOK = "tracecore_ic_dossier_sections"
MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
MASKED = re.compile(r"^\*{3}[^*]{0,4}$")
MAX_MONTHS = 60
# ngoài cột cấm của exporter: tên/mã nhân viên phơi nhiễm, mã BN nguồn (FR-M16-06, Q3 A-152)
EXTRA_FORBIDDEN = frozenset(
	{"employee", "employee_name", "source_patient_code", "source_patient_code_hash", "patient_hash"}
)

__all__ = ["DossierPrivacyError", "DossierSection", "ExportField"]


class DossierPrivacyError(frappe.ValidationError):
	"""Một phần của gói có cột hoặc giá trị lộ dữ liệu cá nhân (UC-57 E5)."""


@dataclass
class DossierSection:
	key: str
	label: str  # nhãn tiếng Anh, dịch theo ngôn ngữ người xuất (tên sheet, tiêu đề PDF)
	order: int
	fields: list[ExportField]
	rows: Callable[[dict], list[dict]]
	in_pdf: bool = True  # False: danh sách chi tiết chỉ ở Excel (Q3 A-152)


def forbidden(name) -> bool:
	name = (name or "").strip().lower()
	return name in exporter.FORBIDDEN_FIELDS or name in EXTRA_FORBIDDEN


def _privacy_error(section, detail):
	return DossierPrivacyError(_("Dossier section {0} was not exported: {1}").format(section.key, detail))


def check_section(section):
	"""Chặn phần khai báo cột có thể chứa dữ liệu cá nhân dạng rõ."""
	for item in section.fields:
		if forbidden(item.field):
			raise _privacy_error(
				section, _("column {0} would put personal data in the file").format(item.field)
			)
	return section


def check_rows(section, rows):
	"""Mọi cột ``*_masked`` phải đã che; trả lại ``rows``."""
	masked = [item.field for item in section.fields if item.field.endswith("_masked")]
	for row in rows:
		for field in masked:
			value = row.get(field)
			if value not in (None, "") and not MASKED.match(str(value)):
				raise _privacy_error(section, _("column {0} holds a code that is not masked").format(field))
	return rows


def sections(keys=None) -> list[DossierSection]:
	"""Các phần đã đăng ký theo thứ tự; ``keys`` (list) chọn bớt, khóa lạ → lỗi."""
	found: dict[str, DossierSection] = {}
	for result in extension.run(HOOK):
		for section in result or []:
			found[section.key] = check_section(section)
	if keys:
		unknown = [key for key in keys if key not in found]
		if unknown:
			frappe.throw(_("Unknown dossier section: {0}").format(", ".join(unknown)))
		found = {key: section for key, section in found.items() if key in keys}
	return sorted(found.values(), key=lambda section: (section.order, section.key))


def months(from_month, to_month) -> list[str]:
	"""Các tháng ``YYYY-MM`` từ ``from_month`` đến ``to_month`` (gồm hai đầu)."""
	start, end = MONTH.match(from_month or ""), MONTH.match(to_month or "")
	if not start or not end:
		frappe.throw(_("Months must be in the form YYYY-MM, for example 2026-10."))
	year, month = int(start.group(1)), int(start.group(2))
	stop = (int(end.group(1)), int(end.group(2)))
	if (year, month) > stop:
		frappe.throw(_("The from month is after the to month."))
	out = []
	while (year, month) <= stop:
		out.append(f"{year:04d}-{month:02d}")
		if len(out) > MAX_MONTHS:
			frappe.throw(_("A dossier covers at most {0} months.").format(MAX_MONTHS))
		year, month = (year + 1, 1) if month == 12 else (year, month + 1)
	return out


def context(from_month, to_month):
	"""Ngữ cảnh truyền cho hàm lấy dòng: ``from_date``, ``to_date`` (ngày), ``months``, ``years``."""
	items = months(from_month, to_month)
	from_date = getdate(f"{items[0]}-01")
	to_date = get_last_day(getdate(f"{items[-1]}-01"))
	return frappe._dict(
		from_date=from_date,
		to_date=to_date,
		months=items,
		years=sorted({int(item[:4]) for item in items}),
	)


def month_range(from_date, to_date):
	"""(tháng đầu, tháng cuối) ``YYYY-MM`` của một dải ngày (phiếu `Archive Export`)."""
	return getdate(from_date).strftime("%Y-%m"), getdate(to_date).strftime("%Y-%m")
