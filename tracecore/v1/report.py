"""RPC tracecore.v1.report.* — xuất PDF nền sổ tiệt khuẩn / báo cáo KSNK / dự báo, khóa kỳ báo cáo (FEAT-007, A-57).

Đường Desk (không phải trạm/PDA nên không `@idempotent`). `export` kiểm quyền Script Report tương ứng, kiểm bộ lọc rồi
xếp job RQ ``long`` (NFR-PERF-03); người xuất nhận chuông Desk và realtime ``tc_report_ready`` khi PDF xong.
`sterilization_log` là tên RPC trong implementation-plan. `lock_period`: chỉ TC R01 (A-57 Q3).
"""

import frappe
from frappe import _

from tracecore.admin_reports import sterilization_log as slog

LOCK_ROLE = "TC R01"
JOB_TIMEOUT = 600


@frappe.whitelist(methods=["POST"])
def export(kind, filters=None):
	"""Xếp job sinh PDF loại `kind` với `filters` (JSON); trả ``{"ok", "job"}``."""
	if kind not in slog.KINDS:
		frappe.throw(_("Unknown report: {0}").format(kind))
	if not frappe.get_doc("Report", slog.KINDS[kind]["report"]).is_permitted():
		raise frappe.PermissionError(_("You cannot export this report."))
	filters = frappe._dict(frappe.parse_json(filters) if isinstance(filters, str) else (filters or {}))
	if kind != "life_forecast":
		slog.period(filters)
	job = frappe.enqueue(
		"tracecore.admin_reports.sterilization_log.build_export",
		queue="long",
		timeout=JOB_TIMEOUT,
		kind=kind,
		filters=dict(filters),
		user=frappe.session.user,
		lang=frappe.local.lang,
	)
	return {"ok": True, "job": getattr(job, "id", None)}


@frappe.whitelist(methods=["POST"])
def sterilization_log(filters=None):
	return export("sterilization_log", filters)


@frappe.whitelist(methods=["POST"])
def lock_period(until):
	"""R01 đặt ngày khóa báo cáo: kỳ kết thúc trước hoặc bằng ngày này in bản chính thức (FR-M9-02.1)."""
	if LOCK_ROLE not in frappe.get_roles():
		raise frappe.PermissionError(
			_("Only the head of infection control (R01) can lock the report period.")
		)
	return {"ok": True, "locked_until": str(slog.lock_period(until))}
