"""RPC tracecore.v1.environment.* — SCR-62 Vệ sinh môi trường & cơ sở hạ tầng (FEAT-070; FR-M15-01..07; UC-54; A-148 f).

- ``overview`` (GET): màn WEB trong Page `tc-ksnk` (slug ``moi-truong``): KPI tháng, mẫu Không đạt chờ quyết định NC,
  mẫu môi trường, vùng (đủ/thiếu phiếu, cờ chờ lấy mẫu lại), hạ tầng (hạn kế tiếp, trạng thái), ngưỡng đang hiệu lực,
  kế hoạch lấy mẫu và mẫu trễ hạn, tỷ lệ đạt theo mức nguy cơ/khoa/bên chịu trách nhiệm. R13 chỉ nhận số liệu tổng hợp.
- ``open_nc``, ``dismiss_nc`` (POST, ``@idempotent``): R01/R11 quyết định NC Environment của mẫu Không đạt; lỗi nghiệp vụ
  trả ``{ok: false, error: {code, title, reason, action}}`` để màn hiện ``alert-error`` inline.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.environmental_hygiene import audits, limits, plans, report_data, samples, zones
from tracecore.ui import ksnk
from tracecore.v1._common import reject_block

SCREEN_SLUG = "moi-truong"
SUMMARY_ONLY_ROLES = frozenset({"TC R13"})
DETAIL_ROLES = frozenset({"TC R01", "TC R02", "TC R11", "System Manager"})
SAMPLE_KEYS = (
	"name",
	"environment_zone",
	"environment_zone_name",
	"sample_type",
	"sampled_on",
	"result_value",
	"unit",
	"limit_applied",
	"result",
	"is_resample_of",
	"nc_status",
	"nc_name",
)


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == SCREEN_SLUG)
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(
			_("You are not allowed to open the environmental hygiene screen."), frappe.PermissionError
		)


def _summary_only():
	roles = set(frappe.get_roles())
	return (
		frappe.session.user != "Administrator"
		and bool(roles & SUMMARY_ONLY_ROLES)
		and not roles & DETAIL_ROLES
	)


def _limits(on):
	codes = frappe.get_all(limits.DOCTYPE, filters={"docstatus": 1}, pluck="limit_code", distinct=True)
	rows = []
	for code in sorted(set(codes)):
		name = limits.active_limit(code, on)
		if not name:
			continue
		doc = frappe.get_doc(limits.DOCTYPE, name)
		rows.append(
			{
				"name": doc.name,
				"title": doc.title,
				"sample_type": doc.sample_type,
				"method": doc.method,
				"applies_to_risk_level": doc.applies_to_risk_level,
				"snapshot": limits.snapshot(doc),
				"effective_from": doc.effective_from,
			}
		)
	drafts = frappe.db.count(limits.DOCTYPE, {"docstatus": 0})
	return rows, cint(drafts)


def _plans():
	result = []
	for plan in frappe.get_all(
		plans.DOCTYPE,
		filters={"active": 1},
		fields=["name", "title", "sample_type", "frequency", "assignee_name"],
		order_by="title asc",
	):
		plan["zones"] = frappe.get_all(
			plans.ROW_DOCTYPE,
			filters={"parent": plan.name, "parenttype": plans.DOCTYPE},
			fields=["environment_zone", "environment_zone_name", "next_due", "last_sampled_on"],
			order_by="next_due asc",
		)
		result.append(plan)
	return result


def _perms(*doctypes):
	"""Cờ hiện nút theo quyền DocType (A-131); quyền thật vẫn kiểm ở DocPerm khi mở form."""
	return {
		doctype: {
			"write": bool(frappe.has_permission(doctype, "write")),
			"create": bool(frappe.has_permission(doctype, "create")),
		}
		for doctype in doctypes
	}


@frappe.whitelist(methods=["GET"])
def overview(month=None):
	"""Dữ liệu SCR-62 cho tháng chứa ``month`` (YYYY-MM-DD hoặc YYYY-MM; trống = hôm nay)."""
	_require_screen()
	on = getdate(f"{month}-01" if month and len(month) == 7 else (month or today()))
	data = report_data.build(report_data.MONTH, on)
	passed, total = data["high_risk"]
	systems = data["infrastructure"]["rows"]
	kpis = {
		"high_risk_passed": passed,
		"high_risk_total": total,
		"samples_failed": data["samples"]["failed"],
		"samples_total": data["samples"]["total"],
		"samples_overdue": len(data["overdue_samples"]),
		"infra_due_soon": sum(1 for row in systems if row["status"] == audits.DUE_SOON),
		"infra_overdue": sum(1 for row in systems if row["status"] == audits.OVERDUE),
		"zones_short": len(data["coverage"]),
	}
	result = {
		"month": on.strftime("%Y-%m"),
		"summary_only": _summary_only(),
		"kpis": kpis,
		"rates": data["hygiene"],
		"infra_by_category": data["infrastructure"]["by_category"],
		"chemicals_litres": data["chemicals"]["litres"],
	}
	if result["summary_only"]:
		return result
	limit_rows, drafts = _limits(today())
	pending = frappe.get_all(
		samples.DOCTYPE,
		filters={"docstatus": 1, "nc_status": samples.SUGGESTED},
		fields=list(SAMPLE_KEYS),
		order_by="sampled_on desc",
		limit=20,
	)
	# Mẫu lại Đạt đã gỡ cờ vùng: vẫn chờ quyết định NC (BRU-ENV-003) nhưng màn không được nói vùng còn giữ cờ
	resolved = {}
	for row in pending:
		if row.environment_zone not in resolved:
			resolved[row.environment_zone] = zones.resolving_resamples(row.environment_zone)
		row["resolved_by"] = resolved[row.environment_zone].get(row.name)
	result.update(
		{
			"can_decide": samples.can_decide(),
			"perms": _perms(samples.DOCTYPE, "Environment Zone", "Sampling Plan", "Environmental Limit"),
			"pending_nc": pending,
			"samples": [{key: row.get(key) for key in SAMPLE_KEYS} for row in data["samples"]["rows"][:50]],
			"zones": zones.coverage(on),
			"infrastructure": systems,
			"limits": limit_rows,
			"limit_drafts": drafts,
			"plans": _plans(),
			"overdue_samples": data["overdue_samples"],
		}
	)
	return result


@frappe.whitelist(methods=["POST"])
@idempotent
def open_nc(sample=None, client_ts=None):
	"""R01/R11 mở NC Environment cho mẫu Không đạt: ``{ok, incident}``."""
	timestamp = parse_client_ts(client_ts) if client_ts else None
	try:
		incident = samples.open_nc(sample)
	except BlockedError as error:
		return reject_block(error.block, samples.DOCTYPE, sample, client_ts=timestamp)
	return {"ok": True, "incident": incident}


@frappe.whitelist(methods=["POST"])
@idempotent
def dismiss_nc(sample=None, reason=None, client_ts=None):
	"""R01/R11 không mở NC, bắt buộc lý do: ``{ok}``."""
	timestamp = parse_client_ts(client_ts) if client_ts else None
	try:
		samples.dismiss_nc(sample, reason)
	except BlockedError as error:
		return reject_block(error.block, samples.DOCTYPE, sample, client_ts=timestamp)
	return {"ok": True}
