"""RPC tracecore.v1.wastewater.* — SCR-67 Nước thải y tế (FEAT-095; FR-M15-08..13; UC-58; A-153 §3.4).

- ``overview`` (GET): màn WEB trong Page `tc-ksnk` (slug ``nuoc-thai``): KPI năm, GPMT hiện hành (hạn, badge ≤ 90 ngày),
  lịch điểm x kỳ, điểm đang cờ vượt chuẩn, đợt gần nhất từng điểm, đơn vị quan trắc VIMCERTS. R13 chỉ nhận KPI.
- ``schedule`` (GET): lịch năm; ``parameters`` (GET): thông số theo GPMT hiệu lực tại ngày lấy mẫu cho form đợt;
  ``template`` (GET): dòng mẫu quy chuẩn để nạp vào GPMT Nháp.
- ``new_permit_version``, ``open_nc``, ``dismiss_nc`` (POST, ``@idempotent``): chỉ R01; lỗi nghiệp vụ trả
  ``{ok: false, error: {code, title, reason, action}}`` để màn hiện ``alert-error`` inline.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.environmental_hygiene import wastewater, wastewater_schedule
from tracecore.ui import ksnk
from tracecore.v1._common import reject_block

SCREEN_SLUG = "nuoc-thai"
SUMMARY_ONLY_ROLES = frozenset({"TC R13"})
DETAIL_ROLES = frozenset({"TC R01", "TC R02", "TC R11", "System Manager"})
LAB_WARNING_DAYS = 30
ROUND_KEYS = (
	"name",
	"wastewater_point",
	"point_name",
	"point_type",
	"sampled_on",
	"period_label",
	"supplier_name",
	"vimcerts_no",
	"report_no",
	"wastewater_permit",
	"overall_result",
	"nc_status",
	"nc_name",
)


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == SCREEN_SLUG)
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(_("You are not allowed to open the wastewater screen."), frappe.PermissionError)


def _summary_only():
	roles = set(frappe.get_roles())
	return (
		frappe.session.user != "Administrator"
		and bool(roles & SUMMARY_ONLY_ROLES)
		and not roles & DETAIL_ROLES
	)


def _perms(*doctypes):
	return {
		doctype: {
			"write": bool(frappe.has_permission(doctype, "write")),
			"create": bool(frappe.has_permission(doctype, "create")),
		}
		for doctype in doctypes
	}


def _kpis(grid, on):
	cells = [cell for row in grid if not row["auto_only"] for cell in row["periods"]]
	ended = [cell for cell in cells if cell["status"] not in ("na", "none", "future") and cell["end"] < on]
	current = [cell["days_left"] for cell in cells if cell["status"] in ("due", "miss") and cell["end"] >= on]
	return {
		"points": sum(1 for row in grid if not row["auto_only"] and row["permit"]),
		"on_time": sum(1 for cell in ended if cell["status"] in wastewater_schedule.MONITORED),
		"total_periods": len(ended),
		"overdue": sum(1 for cell in ended if cell["status"] in ("over", "miss")),
		"flagged": sum(1 for row in grid if row["awaiting_remonitor"]),
		"days_left_period": min(current) if current else None,
	}


def _permits(on):
	result = []
	for row in wastewater.current_permits(on):
		doc = frappe.get_doc(wastewater.PERMIT_DOCTYPE, row.name)
		days = wastewater.days_to_expiry(doc, on)
		previous = frappe.db.get_value(
			wastewater.PERMIT_DOCTYPE, {"superseded_by": doc.name, "docstatus": 1}, "name"
		)
		result.append(
			{
				"name": doc.name,
				"permit_code": doc.permit_code,
				"permit_no": doc.permit_no,
				"standard": doc.standard,
				"standard_column": doc.standard_column,
				"factor_note": doc.factor_note,
				"issuing_authority": doc.issuing_authority,
				"effective_from": doc.effective_from,
				"valid_until": doc.valid_until,
				"days_to_expiry": days,
				"expiring": days is not None and days <= wastewater.EXPIRY_WARNING_DAYS,
				"previous": previous,
			}
		)
	return result


def _results(round_name, permit, point):
	limits = (
		{(row.parameter or "").strip().lower(): row for row in wastewater.permit_rows(permit, point)}
		if permit
		else {}
	)
	rows = frappe.get_all(
		wastewater.RESULT_DOCTYPE,
		filters={"parenttype": wastewater.DOCTYPE, "parent": round_name},
		fields=["parameter", "unit", "value", "below_detection", "limit_applied", "result"],
		order_by="idx asc",
	)
	for row in rows:
		limit = limits.get((row.parameter or "").strip().lower())
		row["limit_text"] = wastewater.band(limit) if limit else "—"
	return rows


def _latest(grid):
	latest = []
	for row in grid:
		found = frappe.get_all(
			wastewater.DOCTYPE,
			filters={"wastewater_point": row["point"], "docstatus": 1},
			fields=list(ROUND_KEYS),
			order_by="sampled_on desc, creation desc",
			limit=1,
		)
		if found:
			item = found[0]
			item["results"] = _results(item.name, item.wastewater_permit, item.wastewater_point)
			latest.append(item)
	return latest


def _flagged(grid):
	result = []
	for row in grid:
		if not row["awaiting_remonitor"] or not row["flag_monitoring"]:
			continue
		doc = frappe.db.get_value(
			wastewater.DOCTYPE, row["flag_monitoring"], ["sampled_on", "nc_status", "nc_name"], as_dict=True
		)
		failed = frappe.get_all(
			wastewater.RESULT_DOCTYPE,
			filters={
				"parenttype": wastewater.DOCTYPE,
				"parent": row["flag_monitoring"],
				"result": wastewater.FAIL,
			},
			pluck="parameter",
		)
		result.append(
			{
				"point": row["point"],
				"point_name": row["point_name"],
				"monitoring": row["flag_monitoring"],
				"sampled_on": doc and doc.sampled_on,
				"nc_status": doc and doc.nc_status,
				"nc_name": doc and doc.nc_name,
				"failed": failed,
			}
		)
	return result


def _labs(on):
	rows = frappe.get_all(
		"Supplier",
		filters={"tc_vimcerts_no": ["is", "set"]},
		fields=["name", "supplier_name", "tc_vimcerts_no", "tc_vimcerts_valid_until"],
		order_by="supplier_name asc",
	)
	result = []
	for row in rows:
		until = row.tc_vimcerts_valid_until and getdate(row.tc_vimcerts_valid_until)
		result.append(
			{
				"supplier": row.name,
				"supplier_name": row.supplier_name,
				"vimcerts_no": row.tc_vimcerts_no,
				"valid_until": until,
				"expired": bool(until and until < on),
				"expiring": bool(until and on <= until and (until - on).days <= LAB_WARNING_DAYS),
			}
		)
	return result


def _day(on):
	return getdate(on or today())


@frappe.whitelist(methods=["GET"])
def overview(year=None, on=None):
	"""Dữ liệu SCR-67 cho năm ``year`` (trống = năm của hôm nay)."""
	_require_screen()
	on = _day(on)
	year = cint(year) or on.year
	grid = wastewater_schedule.grid(year, on)
	result = {
		"year": year,
		"today": on,
		"summary_only": _summary_only(),
		"kpis": _kpis(grid, on),
	}
	if result["summary_only"]:
		return result
	result.update(
		{
			"can_decide": wastewater.can_decide(),
			"perms": _perms(wastewater.DOCTYPE, wastewater.PERMIT_DOCTYPE, wastewater.POINT_DOCTYPE),
			"permits": _permits(on),
			"drafts": frappe.db.count(wastewater.PERMIT_DOCTYPE, {"docstatus": 0}),
			"schedule": grid,
			"flagged": _flagged(grid),
			"latest": _latest(grid),
			"labs": _labs(on),
		}
	)
	return result


@frappe.whitelist(methods=["GET"])
def schedule(year=None, on=None):
	_require_screen()
	on = _day(on)
	return wastewater_schedule.grid(cint(year) or on.year, on)


@frappe.whitelist(methods=["GET"])
def parameters(point=None, sampled_on=None):
	"""Thông số của điểm theo GPMT hiệu lực tại ngày lấy mẫu (form đợt quan trắc)."""
	_require_screen()
	frappe.has_permission(wastewater.DOCTYPE, "read", throw=True)
	on = _day(sampled_on)
	permit = wastewater.active_permit(point, on)
	if not permit:
		return {"permit": None, "standard": None, "results": []}
	doc = frappe.get_doc(wastewater.PERMIT_DOCTYPE, permit)
	return {
		"permit": permit,
		"standard": f"{doc.standard} · {doc.standard_column}",
		"results": [
			{"parameter": row.parameter, "unit": row.unit, "limit_text": wastewater.band(row)}
			for row in wastewater.permit_rows(permit, point, include_auto=False)
		],
	}


@frappe.whitelist(methods=["GET"])
def template(standard=None, column=None, point=None, frequency=None):
	_require_screen()
	return wastewater.template(standard, column, point, frequency)


def _require_r01():
	if not wastewater.can_decide():
		frappe.throw(
			_("Only the head of infection control (R01) can change the permit."), frappe.PermissionError
		)


@frappe.whitelist(methods=["POST"])
@idempotent
def new_permit_version(permit=None, client_ts=None):
	"""R01 "Cập nhật GPMT": tạo (hoặc mở) phiên bản Nháp kế tiếp: ``{ok, name}``."""
	_require_r01()
	if client_ts:
		parse_client_ts(client_ts)
	return {"ok": True, "name": wastewater.new_version(permit).name}


@frappe.whitelist(methods=["POST"])
@idempotent
def open_nc(monitoring=None, client_ts=None):
	"""R01 mở NC Environment cho đợt Không đạt: ``{ok, incident}``."""
	timestamp = parse_client_ts(client_ts) if client_ts else None
	try:
		incident = wastewater.open_nc(monitoring)
	except BlockedError as error:
		return reject_block(error.block, wastewater.DOCTYPE, monitoring, client_ts=timestamp)
	return {"ok": True, "incident": incident}


@frappe.whitelist(methods=["POST"])
@idempotent
def dismiss_nc(monitoring=None, reason=None, client_ts=None):
	"""R01 không mở NC, bắt buộc lý do: ``{ok}``."""
	timestamp = parse_client_ts(client_ts) if client_ts else None
	try:
		wastewater.dismiss_nc(monitoring, reason)
	except BlockedError as error:
		return reject_block(error.block, wastewater.DOCTYPE, monitoring, client_ts=timestamp)
	return {"ok": True}
