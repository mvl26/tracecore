"""RPC tracecore.v1.ssi.* — giám sát NKVM SCR-57 (WEB + PDA) và khối NKVM của SCR-58 (FEAT-064; FR-M13-07..09, 12;
UC-49; A-147 j, k).

- ``screen`` / ``detail`` / ``due`` (GET), ``save`` / ``record_followup`` / ``close`` / ``create_case`` (POST): R01, R11.
- ``summary`` (GET): R01, R10, R11, R13 — chỉ số liệu tổng hợp theo nhóm phẫu thuật và NNIS (BRU-RPT-002).
- Mã người bệnh: chỉ bản che; xem đầy đủ dùng ``tracecore.v1.patient_code.reveal`` (lý do, Audit Log).

RPC Desk không ``@idempotent`` (response có dữ liệu ca, như `v1.hai_case`); PDA gọi cùng RPC khi có mạng (màn theo dõi
NKVM không lưu dữ liệu người bệnh trên máy). Từ chối nghiệp vụ trả ``{"ok": false, "error"}``.
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from tracecore.core.errors import BlockedError
from tracecore.hai_surveillance import definitions, periods, ssi, ssi_indicators
from tracecore.v1._common import reject_block, require_any_role

WORK_ROLES = ("TC R01", "TC R11", "System Manager")
REPORT_ROLES = ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager")
EDITABLE = (
	"patient_code",
	"birth_year",
	"sex",
	"department",
	"procedure_group",
	"surgery_date",
	"asa_score",
	"wound_class",
	"duration_min",
	"has_implant",
	"prophylaxis_given",
	"prophylaxis_agent",
	"prophylaxis_minutes_before_incision",
	"discharge_date",
)
FOLLOWUP_FIELDS = ("name", "due_date", "method", "is_final", "done_on", "result", "note", "done_by")


def _guard(ref_name, fn):
	frappe.db.savepoint("tc_ssi")
	try:
		return fn()
	except BlockedError as error:
		frappe.db.rollback(save_point="tc_ssi")
		return reject_block(error.block, ssi.DOCTYPE, ref_name)


def _values(values):
	if isinstance(values, str):
		values = frappe.parse_json(values)
	return {key: values.get(key) for key in EDITABLE if key in (values or {})}


def detail(name):
	if not frappe.has_permission(ssi.DOCTYPE, "read", name):
		raise frappe.PermissionError(_("You are not allowed to read surgical surveillance {0}.").format(name))
	row = frappe.db.get_value(ssi.DOCTYPE, name, list(ssi.LIST_FIELDS), as_dict=True)
	row["followups"] = frappe.get_all(
		ssi.FOLLOWUP,
		filters={"parent": name, "parenttype": ssi.DOCTYPE},
		fields=list(FOLLOWUP_FIELDS),
		order_by="due_date asc",
	)
	row["case_status"] = (
		frappe.db.get_value("HAI Case", row.hai_case, ["status", "docstatus"], as_dict=True)
		if row.hai_case
		else None
	)
	row["period_locked"] = periods.is_locked(row.reporting_period)
	row["window_over"] = bool(row.window_end and getdate(today()) > getdate(row.window_end))
	return row


def _recent(limit=20):
	return [
		dict(row)
		for row in frappe.get_list(
			ssi.DOCTYPE,
			fields=list(ssi.LIST_FIELDS),
			order_by="surgery_date desc, name desc",
			limit_page_length=limit,
		)
	]


def _kpis():
	month = periods.recent_months(2)[1]  # tháng trước: tháng hiện tại còn trong cửa sổ theo dõi
	total = ssi_indicators.totals(month)
	return {
		"under_surveillance": frappe.db.count(ssi.DOCTYPE, {"outcome": ssi.UNDER}),
		"ssi_month": month,
		"ssi_rate": total["ssi_rate"],
		"on_time_rate": total["on_time_rate"],
		"due_today": len(ssi.due_followups()),
	}


SSI_SITES = ("Superficial Incisional SSI", "Deep Incisional SSI", "Organ/Space SSI")


def _ssi_definitions():
	"""Mã định nghĩa ca đã duyệt thuộc vị trí NKVM (theo `infection_site`, không theo chuỗi mã)."""
	return [row for row in definitions.approved_codes() if row.get("infection_site") in SSI_SITES]


@frappe.whitelist(methods=["GET"])
def screen(name=None):
	"""Dữ liệu SCR-57: KPI, nhóm phẫu thuật đang giám sát, ca gần đây (mã che), lần theo dõi đến hạn, ca đang mở."""
	require_any_role(*WORK_ROLES)
	limit = ssi.threshold()
	return {
		"ok": True,
		"kpis": _kpis(),
		"groups": [dict(row) for row in ssi.monitored_groups()],
		"recent": _recent(),
		"due": ssi.due_followups(),
		"detail": detail(name) if name else None,
		"threshold": limit,
		"definitions": _ssi_definitions(),
		"can_reveal": bool(set(frappe.get_roles()) & {"TC R01", "TC R11"}),
		"can_write": bool(frappe.has_permission(ssi.DOCTYPE, "write")),
		"can_create": bool(frappe.has_permission(ssi.DOCTYPE, "create")),
	}


@frappe.whitelist(methods=["GET"])
def get(name):
	require_any_role(*WORK_ROLES)
	return {"ok": True, "detail": detail(name)}


@frappe.whitelist(methods=["GET"])
def due(day=None):
	"""Lần theo dõi đến hạn/quá hạn (PDA `SSI_FOLLOWUP`, SCR-57)."""
	require_any_role(*WORK_ROLES)
	return {"ok": True, "due": ssi.due_followups(day)}


@frappe.whitelist(methods=["POST"])
def save(values, name=None):
	"""Đăng ký hoặc sửa ca phẫu thuật giám sát (R11, R01); trả chi tiết ca."""
	require_any_role(*WORK_ROLES)
	data = _values(values)

	def run():
		if name:
			if not frappe.has_permission(ssi.DOCTYPE, "write", name):
				raise frappe.PermissionError(
					_("You are not allowed to change surgical surveillance {0}.").format(name)
				)
			doc = frappe.get_doc(ssi.DOCTYPE, name)
			if not data.get("patient_code"):
				data.pop("patient_code", None)
			doc.update(data)
			doc.save()
		else:
			if not frappe.has_permission(ssi.DOCTYPE, "create"):
				raise frappe.PermissionError(_("You are not allowed to register surgical surveillance."))
			doc = frappe.get_doc({"doctype": ssi.DOCTYPE, **data})
			doc.insert()
		return {"ok": True, "detail": detail(doc.name)}

	return _guard(name, run)


@frappe.whitelist(methods=["POST"])
def record_followup(name, row, done_on=None, result=None, note=None):
	require_any_role(*WORK_ROLES)
	return _guard(
		name,
		lambda: {"ok": True, "detail": detail(ssi.record_followup(name, row, done_on, result, note).name)},
	)


@frappe.whitelist(methods=["POST"])
def close(name, outcome, reason=None):
	require_any_role(*WORK_ROLES)
	return _guard(name, lambda: {"ok": True, "detail": detail(ssi.close(name, outcome, reason).name)})


@frappe.whitelist(methods=["POST"])
def create_case(name, def_code, onset_date):
	require_any_role(*WORK_ROLES)

	def run():
		case = ssi.create_case(name, def_code, onset_date)
		return {"ok": True, "case": case.name, "detail": detail(name)}

	return _guard(name, run)


@frappe.whitelist(methods=["GET"])
def summary(period_from=None, period_to=None):
	"""NKVM theo nhóm phẫu thuật và NNIS, KSDP — chỉ tổng hợp (SCR-58)."""
	require_any_role(*REPORT_ROLES)
	months = periods.recent_months(12)
	start = periods.check_month(period_from) if period_from else months[1]
	end = periods.check_month(period_to) if period_to else start
	return {
		"ok": True,
		"period_from": start,
		"period_to": end,
		"months": months,
		"groups": ssi_indicators.summary(start, end),
		"totals": ssi_indicators.totals(start, end),
		"can_export": bool(set(frappe.get_roles()) & {"TC R01", "TC R11"})
		or frappe.session.user == "Administrator",
	}
