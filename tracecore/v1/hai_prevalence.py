"""RPC tracecore.v1.hai_prevalence.* — điều tra cắt ngang (tỷ lệ hiện mắc) trên SCR-58 (FEAT-072; FR-M13-14,
FR-M13-14.1; UC-50 bước 5, 6, E2, E3; A-149 Q1).

- ``overview`` (GET): R01, R10, R11, R13 — ngày điều tra, tỷ lệ hiện mắc theo khoa và toàn viện (chỉ số liệu tổng hợp,
  không mã người bệnh — BRU-RPT-002), mẫu cắt ngang đang hiệu lực, quyền ghi của người gọi.
- ``candidates`` (GET): R01, R11 — người bệnh có đợt thiết bị đang đặt tại khoa vào ngày điều tra, chưa khảo sát (mã che).
- ``record`` (POST): R01, R11 — tạo và ghi sổ một phiếu `Audit Session` cho một người bệnh (mã BN hoặc đợt thiết bị).

Lớp này điều phối engine phiếu M12 (`compliance_audit.prevalence`) và tổng hợp M13 (`hai_surveillance.prevalence`) để
module nghiệp vụ không import nhau (architecture §5.2). RPC Desk không ``@idempotent``: phiếu trùng người bệnh cùng ngày
bị chặn ở engine. Từ chối nghiệp vụ trả ``{"ok": false, "error"}`` (alert-error inline trên màn).
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from tracecore.compliance_audit import prevalence as survey
from tracecore.compliance_audit import templates
from tracecore.core.errors import Block, BlockedError
from tracecore.hai_surveillance import prevalence
from tracecore.v1._common import reject_block, require_any_role

REPORT_ROLES = ("TC R01", "TC R10", "TC R11", "TC R13", "System Manager")
RECORD_ROLES = ("TC R01", "TC R11", "System Manager")
SESSION = "Audit Session"
SAVEPOINT = "tc_prevalence"


def _can_record():
	return bool(set(frappe.get_roles()) & set(RECORD_ROLES))


def active_template(on=None):
	"""Phiên bản đã duyệt đang hiệu lực đầu tiên của các mẫu cắt ngang, hoặc None."""
	for code in survey.template_codes():
		name = templates.active_version(code, on)
		if name:
			return name
	return None


@frappe.whitelist(methods=["GET"])
def overview(date=None):
	require_any_role(*REPORT_ROLES)
	dates = prevalence.survey_dates()
	day = getdate(date) if date else (dates[0] if dates else getdate(today()))
	return {
		"ok": True,
		"dates": dates,
		**prevalence.by_department(day),
		"template": active_template(day),
		"can_record": _can_record(),
	}


@frappe.whitelist(methods=["GET"])
def candidates(date, department):
	require_any_role(*RECORD_ROLES)
	return {"ok": True, "candidates": prevalence.candidates(getdate(date), department)}


def _reject(code, title, reason, action, items=None):
	return reject_block(Block(code, title, reason, action, items=items), SESSION, None)


@frappe.whitelist(methods=["POST"])
def record(date, department, hai, antibiotic=None, device_episode=None, patient_code=None, note=None):
	"""Ghi một người bệnh của đợt điều tra ngày ``date`` tại khoa ``department``."""
	require_any_role(*RECORD_ROLES)
	day = getdate(date)
	if day > getdate(today()):
		return _reject(
			"PREVALENCE_NOT_ALLOWED",
			_("Survey not recorded"),
			_("The survey day {0} is in the future.").format(frappe.format(day, "Date")),
			_("Choose today or an earlier day."),
			items=["date"],
		)
	observer = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")
	if not observer:
		return _reject(
			"PREVALENCE_NOT_ALLOWED",
			_("Survey not recorded"),
			_("Your user is not linked to an active employee, so the observer is unknown."),
			_("Ask the administrator to link your user to your employee record."),
		)
	template = active_template(day)
	if not template:
		return _reject(
			"PREVALENCE_TEMPLATE_MISSING",
			_("Survey template not approved"),
			_("No approved point prevalence survey template is in effect on {0}.").format(
				frappe.format(day, "Date")
			),
			_(
				"Approve the point prevalence survey template on the audit template screen, then record again."
			),
		)
	items = set(frappe.get_all(templates.ITEM_DOCTYPE, filters={"parent": template}, pluck="item_code"))
	answers = [{"item_code": survey.HAI_ITEM, "value": hai or "", "note": note or ""}]
	if survey.ABX_ITEM in items:
		answers.append({"item_code": survey.ABX_ITEM, "value": antibiotic or ""})
	frappe.db.savepoint(SAVEPOINT)
	try:
		doc = frappe.get_doc(
			{
				"doctype": SESSION,
				"audit_template": template,
				"department": department,
				"audit_date": day,
				"observer": observer,
				"mode": "Announced",
				"patient_code": None if device_episode else patient_code,
				"device_episode": device_episode or None,
				"answers": answers,
			}
		)
		doc.insert()
		doc.submit()
	except BlockedError as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		return reject_block(error.block, SESSION, None)
	return {"ok": True, "name": doc.name, "patient_code_masked": doc.patient_code_masked}
