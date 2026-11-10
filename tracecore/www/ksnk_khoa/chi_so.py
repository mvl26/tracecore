"""Cổng khoa — chỉ số KSNK của khoa cạnh toàn viện và việc cần làm (SCR-66 view DEPT, FEAT-065, UC-57 bước 5;
FR-M9-26, FR-M9-26.1; BRU-RPT-001; A-145 D7).

Trang Portal cần đăng nhập; R08/R12 chỉ khoa có User Permission Department, R01/R11 chọn mọi khoa lâm sàng. Chỉ đọc
`IC Indicator Value` đã lưu (``admin_reports.ic_board.department_view``); không tính lại. Trang render ở server, mọi chữ
qua ``_()``; trạng thái luôn có chữ (Đạt / Chưa đạt / Không tính / Chưa đủ mẫu / Không có dữ liệu).
"""

import frappe
from frappe import _

from tracecore.admin_reports import council_report, ic_board

no_cache = 1
ROUTE = "/ksnk-khoa/chi-so"
BADGE = {"Met": "tc-badge-g", "Not met": "tc-badge-r"}
SEVERITY = {"error": "tc-alert-error", "warn": "tc-alert-warn", "info": "tc-alert-info"}


def _value(cell, kind):
	if not cell:
		return "—"
	if cell["value"] is None:
		return _("Not calculated")
	return council_report.number(cell["value"], kind)


def _target(row):
	if not row["target_direction"] or row["target"] is None:
		return "—"
	sign = "≥ " if row["target_direction"] == "Higher is better" else "≤ "
	return sign + council_report.number(row["target"], row["kind"])


def view_rows(data):
	return [
		{
			"code": row["code"],
			"indicator_name": row["indicator_name"],
			"department_value": _value(row["department_value"], row["kind"]),
			"hospital_value": _value(row["hospital_value"], row["kind"]),
			"target": _target(row),
			"status": _(row["status"]),
			"badge": BADGE.get(row["status"], "tc-badge-x"),
			"provisional": bool(row["department_value"] and not row["department_value"]["locked"]),
		}
		for row in data["rows"]
	]


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={ROUTE}"
		raise frappe.Redirect
	context.no_breadcrumbs = 1
	context.show_sidebar = 0
	context.title = _("Department infection control indicators")
	context.ksnk_nav = "chi-so"
	context.forbidden = False
	try:
		data = ic_board.department_view(frappe.form_dict.get("department") or None)
	except frappe.PermissionError:
		frappe.clear_messages()
		context.forbidden = True
		data = ic_board.department_view(None)
	names = {row["name"]: row["label"] for row in data["departments"]}
	context.departments = data["departments"]
	context.department = data["department"]
	context.department_label = names.get(data["department"]) or "-"
	context.period_label = council_report.period_label(data["period"]) if data.get("period") else ""
	context.locked = data.get("locked")
	context.rows = view_rows(data)
	context.todos = [{**item, "cls": SEVERITY[item["severity"]]} for item in data["todos"]]
	return context
