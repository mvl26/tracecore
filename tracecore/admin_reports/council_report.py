"""Báo cáo một trang cho Hội đồng KSNK hằng tháng (FEAT-065; FR-M9-25, FR-M9-25.1, FR-M9-25.2; BRU-RPT-002,
BRU-RPT-003; UC-57 bước 4, A1; ADR-014; A-145 Q2, D5, D6).

- Cron 07:00 (``run_daily``): đúng ngày làm việc thứ ``IC Program Settings.council_report_workday`` (mặc định 5; T2-T6,
  trừ ngày nghỉ trong Holiday List mặc định của Company) thì sinh báo cáo kỳ tháng trước và báo R01, R13.
- Kỳ đã khóa → bản "Chính thức" đọc giá trị đã khóa (không tính lại). Kỳ chưa khóa → engine M9 tạm tính
  (``indicator.compute_period``, chỉ ghi dòng chưa khóa) rồi sinh bản "Tạm"; khi R01 khóa kỳ, ``on_period_locked`` sinh
  lại bản Chính thức.
- Nội dung chỉ số liệu tổng hợp (BRU-RPT-002): chỉ số của kế hoạch năm và việc nổi bật dạng "tiêu đề + số"; không dùng
  ``detail`` của việc cần xử lý, không có tên hay mã người bệnh.
"""

import calendar
import datetime

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, today

from tracecore.admin_reports import ic_board, indicator
from tracecore.core import notification
from tracecore.core.print_tokens import token_values

DOCTYPE = "IC Council Report"
PRINT_FORMAT = "TC IC Council Report"
EVENT = "IC_COUNCIL_REPORT"
SETTINGS = "IC Program Settings"
PROVISIONAL, OFFICIAL = "Provisional", "Official"
DEFAULT_WORKDAY = 5
MAX_WORKDAY = 23  # tháng ít nhất có 20 ngày làm việc trước nghỉ lễ; giữ trong tháng
GENERATE_ROLE = "TC R01"
PDF_OPTIONS = {"page-size": "A4", "orientation": "Portrait", "margin-top": "10mm", "margin-bottom": "10mm"}
UNIT = {"Percentage": " %", "Rate per 1000": " ‰"}
HIGHLIGHT_SEVERITIES = ("error", "warn")


# --- ngày sinh báo cáo -------------------------------------------------------------------------------------------


def workday():
	"""Ngày làm việc thứ mấy của tháng (FR-M9-25.1); trống/0 → 5, quá lớn → 23."""
	value = cint(frappe.db.get_single_value(SETTINGS, "council_report_workday"))
	if value <= 0:
		return DEFAULT_WORKDAY
	return min(value, MAX_WORKDAY)


def _holidays(year, month):
	company = frappe.defaults.get_global_default("company")
	holiday_list = company and frappe.db.get_value("Company", company, "default_holiday_list")
	if not holiday_list:
		return set()
	first = datetime.date(year, month, 1)
	last = datetime.date(year, month, calendar.monthrange(year, month)[1])
	return {
		getdate(day)
		for day in frappe.get_all(
			"Holiday",
			filters={
				"parent": holiday_list,
				"parenttype": "Holiday List",
				"holiday_date": ("between", [first, last]),
			},
			pluck="holiday_date",
		)
	}


def report_day(year, month):
	"""Ngày làm việc thứ ``workday()`` của tháng: bỏ T7, CN và ngày nghỉ của Holiday List mặc định."""
	wanted = workday()
	holidays = _holidays(year, month)
	count = 0
	for number in range(1, calendar.monthrange(year, month)[1] + 1):
		day = datetime.date(year, month, number)
		if day.weekday() >= 5 or day in holidays:
			continue
		count += 1
		if count == wanted:
			return day
	return day  # tháng không đủ ngày làm việc: ngày cuối tháng


def previous_period(day):
	first = getdate(day).replace(day=1)
	last_month = first - datetime.timedelta(days=1)
	return f"{last_month.year:04d}-{last_month.month:02d}"


def run_daily(on=None):
	"""Cron 07:00: sinh báo cáo kỳ tháng trước nếu hôm nay là ngày sinh báo cáo; trả tên báo cáo hoặc None."""
	day = getdate(on or today())
	if day != report_day(day.year, day.month):
		return None
	period = previous_period(day)
	status = frappe.db.get_value(DOCTYPE, {"period": period}, "report_status")
	if status == OFFICIAL or (status == PROVISIONAL and not indicator.is_locked(period)):
		return None  # đã sinh trong ngày (chạy lại) hoặc đã có bản đúng trạng thái kỳ
	return generate(period)


# --- sinh báo cáo ------------------------------------------------------------------------------------------------


def generate(period, notify=True):
	"""Sinh (hoặc sinh lại) báo cáo kỳ ``period`` thành PDF đính kèm; trả tên `IC Council Report`."""
	indicator.check_period(period)
	locked = indicator.is_locked(period)
	if not locked:
		indicator.compute_period(period)  # tạm tính kỳ chưa khóa (chỉ ghi dòng chưa khóa)
	name = frappe.db.get_value(DOCTYPE, {"period": period}, "name")
	doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)
	doc.update(
		{
			"period": period,
			"report_status": OFFICIAL if locked else PROVISIONAL,
			"generated_on": now_datetime(),
		}
	)
	doc.flags.ignore_permissions = True
	doc.save()
	pdf = _pdf(render_html(doc.name))
	for old in frappe.get_all(
		"File", filters={"attached_to_doctype": DOCTYPE, "attached_to_name": doc.name}, pluck="name"
	):
		frappe.delete_doc("File", old, ignore_permissions=True)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name}.pdf",
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": doc.name,
			"attached_to_field": "pdf",
			"is_private": 1,
			"content": pdf,
		}
	).insert(ignore_permissions=True)
	doc.db_set("pdf", file_doc.file_url, update_modified=False)
	if notify:
		_notify(doc, file_doc.file_url)
	return doc.name


def render_html(name):
	return frappe.get_print(DOCTYPE, name, print_format=PRINT_FORMAT, no_letterhead=1)


def _pdf(html):
	from frappe.utils.pdf import get_pdf

	return get_pdf(html, dict(PDF_OPTIONS))


def _notify(doc, file_url):
	label = period_label(doc.period)
	if doc.report_status == OFFICIAL:
		subject = _("Infection control committee report {0} is ready").format(label)
	else:
		subject = _("Provisional infection control committee report {0} is ready").format(label)
	notification.emit(
		EVENT,
		doc,
		subject=subject,
		message=_("One-page report of period {0}, aggregated figures only.").format(label),
		link=file_url,
	)


def on_period_locked(period):
	"""Gọi từ ``indicator.lock_period``: kỳ đã có bản Tạm → sinh lại bản Chính thức (UC-57 A1)."""
	if frappe.db.get_value(DOCTYPE, {"period": period}, "report_status") == PROVISIONAL:
		generate(period)


def todos(user, department=None):
	"""Hook ``tracecore_ksnk_todos``: báo cáo Hội đồng mới nhất (chỉ ở bảng toàn viện)."""
	if department:
		return []
	report = ic_board.latest_council_report()
	if not report:
		return []
	if report.report_status == OFFICIAL:
		title = _("Committee report {0} generated on {1}")
	else:
		title = _("Provisional committee report {0} generated on {1}")
	return [
		{
			"key": "council_report",
			"severity": "info",
			"title": title.format(
				period_label(report.period), get_datetime(report.generated_on).strftime("%d/%m/%Y %H:%M")
			),
			"count": 1,
			"detail": "",
			"link": report.pdf or "",
		}
	]


# --- ngữ cảnh in -------------------------------------------------------------------------------------------------


def period_label(period):
	year, month = period.split("-")
	return f"{month}/{year}"


def number(value, kind=None):
	text = f"{flt(value, 1):,.1f}".replace(",", " ").replace(".", ",").replace(" ", ".")
	if text.endswith(",0"):
		text = text[:-2]
	return text + UNIT.get(kind, "")


def _target_text(row):
	if not row["target_direction"] or row["target"] is None:
		return "—"
	sign = "≥ " if row["target_direction"] == "Higher is better" else "≤ "
	return sign + number(row["target"], row["kind"])


def _value_text(cell, kind):
	if not cell:
		return "—"
	if cell["value"] is None:
		return _("Not calculated")
	return number(cell["value"], kind)


def tc_ic_council_context(name: str) -> dict:
	"""Ngữ cảnh Print Format "TC IC Council Report" — chỉ số liệu tổng hợp (BRU-RPT-002)."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	period = doc.period
	year = cint(period[:4])
	_plan, metas = ic_board.plan_indicators(year)
	periods = ic_board.previous_months(period, ic_board.TABLE_MONTHS)
	stored = ic_board._stored([meta.code for meta in metas], periods, [None])
	rows = []
	met = 0
	for meta in metas:
		cells = [ic_board.cell(stored.get((meta.code, p, None)), meta) for p in periods]
		latest = cells[-1]
		status = latest["status"] if latest else ic_board.NO_DATA
		met += status == "Met"
		rows.append(
			{
				"code": meta.code,
				"indicator_name": meta.indicator_name,
				"target": _target_text(meta),
				"values": [_value_text(cell, meta.kind) for cell in cells],
				"status": status,
				"status_label": _(status) if status else "—",
			}
		)
	highlights = [
		{"title": item["title"], "count": item["count"]}
		for item in ic_board.todos("Administrator", None)
		if item["severity"] in HIGHLIGHT_SEVERITIES
	]
	return {
		"tc": token_values(),
		"name": doc.name,
		"period_label": period_label(period),
		"provisional": doc.report_status != OFFICIAL,
		"generated_on": get_datetime(doc.generated_on).strftime("%d/%m/%Y %H:%M") if doc.generated_on else "",
		"period_headers": [period_label(p) for p in periods],
		"rows": rows,
		"met": met,
		"total": len(rows),
		"highlights": highlights,
	}
