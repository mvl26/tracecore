"""Gói hồ sơ KSNK cho đoàn kiểm tra theo kỳ (FEAT-074; FR-M9-30, FR-M9-30.1; BRU-RPT-002; NFR-PRIV-01; UC-57 bước 8,
A1, A4, E5; A-152).

- Tái dùng `Archive Export` (FEAT-012) với phạm vi ``IC Dossier``: R01 chọn dải tháng ``YYYY-MM`` (Q1) và các phần; job
  RQ ``long`` của `archive.build` gọi ``build_files`` rồi nén ZIP, ghi SHA-256, báo người xuất như hồ sơ tiệt khuẩn.
- Phần của gói do module đăng ký qua hook ``tracecore_ic_dossier_sections`` (`core.dossier`); M9 không import M11-M16.
  M9 tự đóng góp chỉ số (`IC Indicator Value`), báo cáo Hội đồng và tự đánh giá QĐ 38 (``register``).
- Chỉ R01 tạo gói (Q2); không bao giờ xuất mã BN đầy đủ (BRU-RPT-002). Mọi phần qua ``dossier.check_rows``: cột mã chỉ
  dạng che, lộ mã → lỗi, phiếu Failed, không file (UC-57 E5).
- Tháng chưa khóa (`IC Reporting Period.locked` = 0 hoặc chưa có kỳ) → chỉ số tạm tính như báo cáo Hội đồng và gói mang
  dấu "Tạm" (UC-57 A1).
- File: ``ksnk_dossier.pdf`` (bìa + bảng các phần tổng hợp, danh sách chi tiết chỉ ghi số dòng), ``ksnk_dossier.xlsx``
  (mỗi phần một sheet).
"""

import json

import frappe
from frappe import _
from frappe.utils import escape_html, flt, get_fullname, get_last_day, getdate

from tracecore.admin_reports import indicator
from tracecore.core import dossier, exporter, print_tokens
from tracecore.core.dossier import DossierSection, ExportField

SCOPE = "IC Dossier"
ROLE = "TC R01"
PERIOD_DOCTYPE = "IC Reporting Period"
TEMPLATE_PATH = ("admin_reports", "print", "ic_dossier.html")
DATE_FORMAT = "%d/%m/%Y"
PDF_OPTIONS = {"page-size": "A4", "orientation": "Landscape", "margin-top": "10mm", "margin-bottom": "10mm"}
PDF_MAX_ROWS = 500  # bảng dài hơn chỉ ở Excel (UC-57 A4: gói lớn vẫn chạy nền)
INCLUDES = ("inc_loads", "inc_indicators", "inc_machine_data", "inc_issues", "inc_usage", "inc_audit")


# --- phiếu ------------------------------------------------------------------------------------------------------


def can_export(user=None) -> bool:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	return user == "Administrator" or ROLE in roles or "System Manager" in roles


def selected_keys(value) -> list[str]:
	if not value:
		return []
	keys = frappe.parse_json(value) if isinstance(value, str) else value
	if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
		frappe.throw(_("Sections must be a list of section keys."))
	return list(dict.fromkeys(keys))


def validate_export(doc):
	"""``ArchiveExport.validate`` cho phạm vi IC Dossier (phiếu mới)."""
	if not can_export():
		frappe.throw(_("Only the head of infection control (R01) can export the infection control dossier."))
	if doc.full_patient_code:
		frappe.throw(_("The infection control dossier only carries masked patient codes."))
	if not doc.from_date or not doc.to_date:
		frappe.throw(_("Choose the months of the dossier."))
	first, last = dossier.month_range(doc.from_date, doc.to_date)
	months = dossier.months(first, last)
	keys = selected_keys(doc.ic_sections)
	if keys:
		dossier.sections(keys)  # khóa lạ → lỗi
	doc.from_date = getdate(f"{months[0]}-01")
	doc.to_date = get_last_day(getdate(f"{months[-1]}-01"))
	doc.ic_months = f"{months[0]}..{months[-1]}"
	doc.ic_sections = json.dumps(keys) if keys else None
	doc.sterilization_load = doc.recall_order = doc.patient_code_reason = None
	for field in INCLUDES:
		doc.set(field, 0)


# --- gom dữ liệu -------------------------------------------------------------------------------------------------


def unlocked_months(months) -> list[str]:
	locked = set(
		frappe.get_all(PERIOD_DOCTYPE, filters={"month": ["in", months], "locked": 1}, pluck="month")
	)
	return [month for month in months if month not in locked]


def collect(doc):
	"""``{ctx, sections: [(DossierSection, rows)]}`` của phiếu; rows đã qua kiểm mã che."""
	ctx = dossier.context(*dossier.month_range(doc.from_date, doc.to_date))
	chosen = dossier.sections(selected_keys(doc.ic_sections) or None)
	return frappe._dict(
		ctx=ctx,
		sections=[(section, dossier.check_rows(section, section.rows(ctx) or [])) for section in chosen],
	)


def _cell(item, value):
	return exporter._value(item, value, DATE_FORMAT)


def _pdf_text(item, value):
	value = _cell(item, value)
	if isinstance(value, float):
		text = f"{value:,.2f}".rstrip("0").rstrip(".")
		return text.replace(",", " ").replace(".", ",").replace(" ", ".")
	return "" if value is None else str(value)


def _month_label(month):
	return f"{month[5:]}/{month[:4]}"


def render_html(collected, provisional, generated_at, requested_by):
	ctx = collected.ctx
	hospital = frappe.defaults.get_global_default("company") or ""
	sections = []
	for section, rows in collected.sections:
		printable = section.in_pdf and len(rows) <= PDF_MAX_ROWS
		sections.append(
			{
				"key": section.key,
				"label": _(section.label),
				"count": len(rows),
				"printable": printable,
				"headers": [_(item.label) for item in section.fields],
				"numeric": [item.kind in ("int", "float") for item in section.fields],
				"rows": [[_pdf_text(item, row.get(item.field)) for item in section.fields] for row in rows]
				if printable
				else [],
			}
		)
	context = {
		"tc": print_tokens.token_values(),
		"title": _("Infection control dossier"),
		"hospital": hospital,
		"months": _("Months {0} to {1}").format(_month_label(ctx.months[0]), _month_label(ctx.months[-1])),
		"generated": _("Exported by {0} at {1}").format(get_fullname(requested_by), generated_at),
		"provisional": provisional,
		"sections": sections,
	}
	with open(frappe.get_app_path("tracecore", *TEMPLATE_PATH), encoding="utf-8") as handle:
		body = frappe.render_template(handle.read(), {"r": frappe._dict(context)})
	lang = escape_html(frappe.local.lang or "vi")
	return (
		f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
		f"<title>{escape_html(context['title'])}</title>\n</head>\n"
		f'<body>\n<div class="print-format">\n{body}\n</div>\n</body>\n</html>\n'
	)


def _sheet_name(label, used):
	base = "".join(ch for ch in label if ch not in "[]:*?/\\")[:31] or "Sheet"
	name, number = base, 2
	while name.lower() in used:
		suffix = f" ({number})"
		name, number = base[: 31 - len(suffix)] + suffix, number + 1
	used.add(name.lower())
	return name


def _xlsx_value(value):
	from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

	return ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value


def to_xlsx(collected) -> bytes:
	"""Một workbook, mỗi phần một sheet theo thứ tự (tiêu đề dịch theo ngôn ngữ người xuất)."""
	import io

	from openpyxl import Workbook

	book, used = Workbook(write_only=True), set()
	for section, rows in collected.sections:
		sheet = book.create_sheet(_sheet_name(_(section.label), used))
		sheet.append([_(item.label) for item in section.fields])
		for row in rows:
			sheet.append([_xlsx_value(_cell(item, row.get(item.field))) for item in section.fields])
	if not collected.sections:
		book.create_sheet("Data").append([_("No data")])
	out = io.BytesIO()
	book.save(out)
	return out.getvalue()


def build_files(doc, generated_at):
	"""(files ``[(tên, bytes, số dòng)]``, provisional 0/1, phạm vi thêm cho manifest)."""
	from frappe.utils.pdf import get_pdf

	collected = collect_with_values(doc)
	ctx = collected.ctx
	provisional = int(bool(collected.unlocked))
	html = render_html(collected, provisional, generated_at, doc.requested_by)
	files = [
		("ksnk_dossier.pdf", get_pdf(html, dict(PDF_OPTIONS)), None),
		("ksnk_dossier.xlsx", to_xlsx(collected), sum(len(rows) for _section, rows in collected.sections)),
	]
	scope = {
		"months": ctx.months,
		"unlocked_months": collected.unlocked,
		"sections": [section.key for section, _rows in collected.sections],
		"section_rows": {section.key: len(rows) for section, rows in collected.sections},
	}
	return files, provisional, scope


def collect_with_values(doc):
	"""Tạm tính chỉ số tháng chưa khóa (UC-57 A1) rồi gom; thêm ``unlocked``."""
	first, last = dossier.month_range(doc.from_date, doc.to_date)
	unlocked = unlocked_months(dossier.months(first, last))
	for month in unlocked:
		indicator.compute_period(month)
	collected = collect(doc)
	collected.unlocked = unlocked
	return collected


# --- phần của M9 (hook tracecore_ic_dossier_sections) ------------------------------------------------------------


def indicator_rows(ctx):
	rows = frappe.get_all(
		"IC Indicator Value",
		filters={"period": ["in", ctx.months]},
		fields=[
			"indicator",
			"indicator_name",
			"period",
			"department",
			"department_name",
			"numerator",
			"denominator",
			"value",
			"sample_size",
			"sample_note",
			"locked",
		],
		order_by="indicator asc, period asc, department asc",
	)
	for row in rows:
		row.value = indicator.display_value(row)
		row.department_name = row.department_name or (_("Whole hospital") if not row.department else "")
	return rows


def council_rows(ctx):
	return frappe.get_all(
		"IC Council Report",
		filters={"period": ["in", ctx.months]},
		fields=["name", "period", "report_status", "generated_on"],
		order_by="period asc",
	)


def self_assessment_rows(ctx):
	rows = []
	for doc in frappe.get_all(
		"IC Self Assessment",
		filters={"year": ["in", ctx.years], "docstatus": ["<", 2]},
		fields=["name", "year", "docstatus"],
		order_by="year asc",
	):
		for item in frappe.get_all(
			"IC Self Assessment Item",
			filters={"parent": doc.name, "parenttype": "IC Self Assessment"},
			fields=["criterion", "criterion_text", "source", "status", "source_ref", "evidence"],
			order_by="idx asc",
		):
			rows.append({"assessment": doc.name, "year": doc.year, **item})
	return rows


def register():
	return [
		DossierSection(
			key="indicators",
			label="Infection control indicators",
			order=10,
			fields=[
				ExportField("indicator", "Indicator Code"),
				ExportField("indicator_name", "Indicator"),
				ExportField("period", "Period"),
				ExportField("department_name", "Department"),
				ExportField("numerator", "Numerator", "float"),
				ExportField("denominator", "Denominator", "float"),
				ExportField("value", "Value", "float"),
				ExportField("sample_size", "Sample Size", "int"),
				ExportField("sample_note", "Sample Note", "select"),
				ExportField("locked", "Locked", "check"),
			],
			rows=indicator_rows,
		),
		DossierSection(
			key="council_reports",
			label="Committee monthly reports",
			order=20,
			fields=[
				ExportField("name", "Report"),
				ExportField("period", "Period"),
				ExportField("report_status", "Status", "select"),
				ExportField("generated_on", "Generated On", "date"),
			],
			rows=council_rows,
		),
		DossierSection(
			key="self_assessment",
			label="Self-assessment Decision 38",
			order=30,
			fields=[
				ExportField("assessment", "Self Assessment"),
				ExportField("year", "Year", "int"),
				ExportField("criterion", "Criterion Code"),
				ExportField("criterion_text", "Criterion"),
				ExportField("source", "Source", "select"),
				ExportField("status", "Status", "select"),
				ExportField("source_ref", "Source Reference"),
				ExportField("evidence", "Evidence"),
			],
			rows=self_assessment_rows,
		),
	]
