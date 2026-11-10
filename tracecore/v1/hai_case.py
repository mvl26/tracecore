"""RPC tracecore.v1.hai_case.* — ca NKBV, kỳ báo cáo (SCR-56) và tỷ suất (SCR-58) (FEAT-063; FR-M13-05, 06, 10, 11,
15; UC-48; A-144 c, g).

- ``screen`` / ``detail`` / ``isolate_options`` (GET), ``decide`` / ``link_isolate`` (POST): R01, R11.
- ``lock_period`` / ``unlock_period`` (POST): R01. Lớp này điều phối M13 (`hai_surveillance.periods`) và engine chỉ số
  M9 (`admin_reports.indicator`) để module nghiệp vụ không import nhau (architecture §5.2).
- ``report`` (GET): R01, R10, R11, R13 — chỉ số liệu tổng hợp, không mã người bệnh (BRU-RPT-002).
- Xem mã người bệnh đầy đủ dùng ``tracecore.v1.patient_code.reveal`` (lý do bắt buộc, Audit Log).

RPC Desk không ``@idempotent``: response có thể chứa dữ liệu ca. Từ chối nghiệp vụ trả ``{"ok": false, "error"}``.
"""

import frappe
from frappe import _

from tracecore.admin_reports import indicator as engine
from tracecore.core.errors import BlockedError
from tracecore.hai_surveillance import cases, definitions, indicators, periods
from tracecore.v1._common import reject_block, require_any_role

CASE_ROLES = ("TC R01", "TC R11", "System Manager")
LOCK_ROLES = ("TC R01", "System Manager")
REPORT_ROLES = ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager")
ISOLATE = "Microbiology Isolate"


def _guard(ref_name, fn):
	frappe.db.savepoint("tc_hai_case")
	try:
		return fn()
	except BlockedError as error:
		frappe.db.rollback(save_point="tc_hai_case")
		return reject_block(error.block, cases.DOCTYPE, ref_name)


def _roles():
	return set(frappe.get_roles())


@frappe.whitelist(methods=["GET"])
def screen(period=None, department=None, status=None):
	"""Danh sách ca (mã che), kỳ báo cáo và quyền thao tác của người gọi."""
	require_any_role(*CASE_ROLES)
	roles = _roles()
	filters = {"department": department or None, "status": status or None}
	if period:
		filters["reporting_period"] = periods.check_month(period)
	months = periods.recent_months()
	return {
		"ok": True,
		"current_period": months[0],
		"current_locked": int(periods.is_locked(months[0])),
		"cases": cases.list_rows(filters),
		"periods": periods.rows(months),
		"definitions": definitions.approved_codes(),
		"can_decide": bool(roles & set(cases.DECIDE_ROLES)) or frappe.session.user == "Administrator",
		"can_reveal": bool(roles & {"TC R01", "TC R11"}),
		"can_lock": bool(roles & set(LOCK_ROLES)) or frappe.session.user == "Administrator",
	}


@frappe.whitelist(methods=["GET"])
def detail(name):
	require_any_role(*CASE_ROLES)
	return {"ok": True, "detail": cases.detail(name)}


@frappe.whitelist(methods=["GET"])
def isolate_options(name):
	"""Chủng vi sinh cùng người bệnh (theo hash) chưa gắn vào ca — chỉ mã chủng, loài, ngày, nhãn đa kháng."""
	require_any_role(*CASE_ROLES)
	if not frappe.has_permission(cases.DOCTYPE, "read", name):
		raise frappe.PermissionError(_("You are not allowed to read case {0}.").format(name))
	hash_value = frappe.db.get_value(cases.DOCTYPE, name, "patient_code_hash")
	if not hash_value:
		return {"ok": True, "isolates": []}
	linked = frappe.get_all("HAI Case Isolate", filters={"parent": name}, pluck="isolate")
	rows = frappe.get_all(
		ISOLATE,
		filters={"patient_code_hash": hash_value, "name": ["not in", linked or [""]]},
		fields=["name", "organism_name", "collected_on", "mdro_flags", "specimen_type"],
		order_by="collected_on desc",
		limit_page_length=20,
	)
	return {"ok": True, "isolates": [dict(row) for row in rows]}


@frappe.whitelist(methods=["POST"])
def decide(name, decision, reason=None, exception_reason=None):
	require_any_role(*CASE_ROLES)
	return _guard(
		name,
		lambda: {
			"ok": True,
			"detail": cases.detail(cases.decide(name, decision, reason, exception_reason).name),
		},
	)


@frappe.whitelist(methods=["POST"])
def link_isolate(name, isolate):
	require_any_role(*CASE_ROLES)
	if not frappe.has_permission(cases.DOCTYPE, "write", name):
		raise frappe.PermissionError(_("You are not allowed to change case {0}.").format(name))
	return _guard(name, lambda: {"ok": True, "detail": cases.detail(cases.link_isolate(name, isolate).name)})


def _period_body(month):
	return {"ok": True, "periods": periods.rows(periods.recent_months()), "month": month}


@frappe.whitelist(methods=["POST"])
def lock_period(month):
	"""R01 khóa kỳ (FR-M13-11) rồi engine M9 tính và khóa `IC Indicator Value` của tháng (FR-M9-27)."""
	require_any_role(*LOCK_ROLES)

	def run():
		periods.lock(month)
		engine.lock_period(month)
		return _period_body(month)

	return _guard(periods.period_name(month) if periods.MONTH.match(str(month or "")) else None, run)


@frappe.whitelist(methods=["POST"])
def unlock_period(month, reason=None):
	"""R01 mở khóa có lý do (Audit Log); giá trị chỉ số mở khóa theo, khóa lại thì tính lại (BRU-RPT-003)."""
	require_any_role(*LOCK_ROLES)

	def run():
		periods.unlock(month, reason)
		engine.unlock_period(month, reason)
		return _period_body(month)

	return _guard(periods.period_name(month) if periods.MONTH.match(str(month or "")) else None, run)


@frappe.whitelist(methods=["GET"])
def report(period=None):
	"""Tỷ suất theo khoa, toàn viện và xu hướng 12 tháng (SCR-58); chỉ số liệu tổng hợp."""
	require_any_role(*REPORT_ROLES)
	months = periods.recent_months(12)
	period = periods.check_month(period) if period else months[0]
	return {
		"ok": True,
		"period": period,
		"locked": int(periods.is_locked(period)),
		"months": [{"month": month, "locked": int(periods.is_locked(month))} for month in months],
		"hospital": indicators.hospital(period),
		"departments": indicators.by_department(period),
		"trend": indicators.trend(period),
	}


@frappe.whitelist(methods=["GET"])
def definition_codes():
	"""Mã định nghĩa ca đã duyệt cho ô chọn trên Desk form `HAI Case` (R08/R12 tạo ca Nghi ngờ khoa mình)."""
	require_any_role("TC R08", "TC R12", *CASE_ROLES)
	return {"ok": True, "definitions": definitions.approved_codes()}
