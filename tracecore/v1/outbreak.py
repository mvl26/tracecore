"""RPC tracecore.v1.outbreak.* — SCR-61 Điều tra ổ dịch & khai báo bệnh truyền nhiễm, banner cụm ca SCR-58 (FEAT-069;
FR-M14-09, .1, FR-M14-10, .1, FR-M13-13; BRU-MDR-004, BRU-MDR-005; UC-53, UC-50; A-150).

- ``overview`` (GET): màn WEB trong Page `tc-ksnk` (slug ``o-dich``) — danh sách ổ dịch (tổng hợp, R13 xem được), chi
  tiết một ổ dịch cho R01/R11 (ca mã BN che, đường cong dịch, hành động), form mở ổ dịch (điền sẵn từ ``alert``),
  cảnh báo cụm ca, khai báo bệnh truyền nhiễm. R13 chỉ số liệu tổng hợp (ADR-010).
- ``cluster_alerts`` (GET): banner SCR-58. ``candidates`` (GET): ca M13/M14 gắn được.
- Ghi (POST, ``@idempotent``): lỗi nghiệp vụ trả ``{ok: false, error: {code, title, reason, action}}``.
- ``portal_context`` (GET): Cổng khoa `/ksnk-khoa/khai-bao` (R08/R12 khoa có User Permission Department).
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.microbiology import clusters, isolation, notifiable, outbreaks, permissions
from tracecore.ui import ksnk
from tracecore.v1._common import reject_block, require_any_role

SCREEN_SLUG = "o-dich"
CANDIDATE_DAYS = 60


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == SCREEN_SLUG)
	if not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(_("You are not allowed to open the outbreak screen."), frappe.PermissionError)


def _can_read_cases():
	return bool(frappe.has_permission(outbreaks.DOCTYPE, "read")) and outbreaks.can_work()


def _can_read_reports():
	return bool(frappe.has_permission(notifiable.DOCTYPE, "read"))


def _date(value):
	return (value or "").replace("T", " ") or None


def _report_summary(rows):
	counts = {}
	for row in rows:
		counts[row["state"]] = counts.get(row["state"], 0) + 1
	return counts


def _departments(allowed=None):
	if allowed is None:
		rows = isolation.clinical_departments()
	else:
		rows = frappe.get_all(
			"Department",
			filters={"name": ["in", allowed or [""]], "disabled": 0},
			fields=["name", "department_name"],
			order_by="department_name asc",
		)
	return [{"name": row.name, "label": row.department_name or row.name} for row in rows]


def _choices():
	return {
		"diseases": notifiable.diseases(),
		"missing_groups": notifiable.missing_groups(),
		"case_states": list(outbreaks.CASE_STATES),
		"sources": list(outbreaks.SOURCES),
	}


@frappe.whitelist(methods=["GET"])
def overview(outbreak=None, alert=None, source_doctype=None, source_name=None):
	"""Dữ liệu SCR-61 WEB (chỉ đọc)."""
	_require_screen()
	can_cases = _can_read_cases()
	summary = outbreaks.summary_rows()
	current = None
	if can_cases:
		name = outbreak or next((row["name"] for row in summary if row["status"] in outbreaks.ACTIVE), None)
		if name and frappe.db.exists(outbreaks.DOCTYPE, name):
			current = outbreaks.detail(name)
	reports = notifiable.list_reports() if _can_read_reports() else []
	result = {
		"ok": True,
		"can_own": outbreaks.can_own() and can_cases,
		"can_work": can_cases,
		"summary": summary,
		"current": current,
		"prefill": (
			outbreaks.prefill_from_alert(alert)
			if alert
			else outbreaks.prefill_from_source(source_doctype, source_name)
		)
		if can_cases and (alert or source_name)
		else None,
		"alerts": clusters.open_alerts() if can_cases else [],
		"rules_configured": clusters.configured(),
		"rule_form": "/app/cluster-alert-rule",
		"disease_form": "/app/communicable-disease",
		"settings_form": "/app/ic-program-settings",
		"reports": reports if can_cases else [],
		"report_summary": _report_summary(reports),
		"departments": _departments(),
		"can_cancel_report": outbreaks.can_work(),
		"print_outbreak": f"/printview?doctype={outbreaks.DOCTYPE}&format=TC%20Outbreak%20Investigation&name=",
		"print_report": f"/printview?doctype={notifiable.DOCTYPE}&format=TC%20Notifiable%20Disease%20Report&name=",
		**_choices(),
	}
	return result


@frappe.whitelist(methods=["GET"])
def cluster_alerts():
	"""Banner cảnh báo cụm ca của SCR-58: cảnh báo chờ xem xét, đã cấu hình ngưỡng chưa (UC-50 E1)."""
	require_any_role("TC R01", "TC R10", "TC R11", "TC R13", "System Manager")
	can_review = bool(set(frappe.get_roles()) & set(clusters.REVIEW_ROLES))
	return {
		"ok": True,
		"configured": clusters.configured(),
		"can_review": can_review,
		"alerts": clusters.open_alerts(),
		"open_link": clusters.DESK_LINK,
		"rule_form": "/app/cluster-alert-rule",
	}


@frappe.whitelist(methods=["GET"])
def candidates(outbreak=None, source_type=None):
	"""Ca NKBV / chủng của các khoa liên quan từ 60 ngày trước ngày bắt đầu, chưa gắn; chỉ mã che."""
	require_any_role(*outbreaks.WORK_ROLES, "System Manager")
	doc = frappe.get_doc(outbreaks.DOCTYPE, outbreak)
	departments = [doc.department, *[row.department for row in doc.departments]]
	since = add_days(getdate(doc.start_date), -CANDIDATE_DAYS)
	if source_type == outbreaks.HAI:
		linked = {row.hai_case for row in doc.cases if row.hai_case}
		rows = frappe.get_all(
			outbreaks.HAI,
			filters={"department": ["in", departments], "onset_date": [">=", since], "docstatus": ["<", 2]},
			fields=[
				"name",
				"patient_code_masked",
				"department",
				"onset_date as date",
				"infection_site as label",
				"status",
			],
			order_by="onset_date desc",
			limit_page_length=200,
		)
	else:
		linked = {row.isolate for row in doc.cases if row.isolate}
		rows = frappe.get_all(
			"Microbiology Isolate",
			filters={"department": ["in", departments], "collected_on": [">=", since]},
			fields=[
				"name",
				"patient_code_masked",
				"department",
				"collected_on as date",
				"organism_name as label",
				"mdro_flags as status",
			],
			order_by="collected_on desc",
			limit_page_length=200,
		)
	return {"ok": True, "rows": [dict(row) for row in rows if row.name not in linked]}


def _run(_fn, _doctype, _ref, _client_ts, *args, **kwargs):
	timestamp = parse_client_ts(_client_ts)
	try:
		return _fn(*args, **kwargs), None
	except BlockedError as error:
		return None, reject_block(error.block, _doctype, _ref, client_ts=timestamp)


def _detail(doc):
	return {"ok": True, "outbreak": outbreaks.detail(doc.name)}


@frappe.whitelist(methods=["POST"])
@idempotent
def open_outbreak(
	title=None,
	organism_or_disease=None,
	organism=None,
	communicable_disease=None,
	department=None,
	departments=None,
	start_date=None,
	case_definition=None,
	cluster_alert=None,
	source=None,
	source_doctype=None,
	source_name=None,
	client_ts=None,
):
	values = {
		"title": title,
		"organism_or_disease": organism_or_disease,
		"organism": organism or None,
		"communicable_disease": communicable_disease or None,
		"department": department or None,
		"departments": json.loads(departments)
		if isinstance(departments, str) and departments
		else departments,
		"start_date": start_date,
		"case_definition": case_definition,
		"cluster_alert": cluster_alert or None,
		"source": source or None,
		"source_doctype": source_doctype or None,
		"source_name": source_name or None,
	}
	doc, rejected = _run(outbreaks.open_outbreak, outbreaks.DOCTYPE, cluster_alert, client_ts, values)
	return rejected or _detail(doc)


@frappe.whitelist(methods=["POST"])
@idempotent
def add_case(
	outbreak=None,
	source_type=None,
	ref=None,
	patient_code=None,
	onset_date=None,
	case_status=None,
	department=None,
	client_ts=None,
):
	doc, rejected = _run(
		outbreaks.add_case,
		outbreaks.DOCTYPE,
		outbreak,
		client_ts,
		outbreak,
		source_type,
		ref=ref or None,
		patient_code=patient_code,
		onset_date=onset_date or None,
		case_status=case_status or None,
		department=department or None,
	)
	return rejected or _detail(doc)


@frappe.whitelist(methods=["POST"])
@idempotent
def remove_case(outbreak=None, row=None, reason=None, client_ts=None):
	doc, rejected = _run(outbreaks.remove_case, outbreaks.DOCTYPE, outbreak, client_ts, outbreak, row, reason)
	return rejected or _detail(doc)


@frappe.whitelist(methods=["POST"])
@idempotent
def add_action(outbreak=None, description=None, responsible=None, due_date=None, client_ts=None):
	doc, rejected = _run(
		outbreaks.add_action,
		outbreaks.DOCTYPE,
		outbreak,
		client_ts,
		outbreak,
		description,
		responsible,
		due_date,
	)
	return rejected or _detail(doc)


@frappe.whitelist(methods=["POST"])
@idempotent
def link_nc(outbreak=None, incident=None, client_ts=None):
	doc, rejected = _run(outbreaks.link_nc, outbreaks.DOCTYPE, outbreak, client_ts, outbreak, incident)
	return rejected or _detail(doc)


@frappe.whitelist(methods=["POST"])
@idempotent
def set_controlled(outbreak=None, client_ts=None):
	doc, rejected = _run(outbreaks.set_controlled, outbreaks.DOCTYPE, outbreak, client_ts, outbreak)
	return rejected or _detail(doc)


@frappe.whitelist(methods=["POST"])
@idempotent
def end_outbreak(
	outbreak=None, summary=None, end_date=None, external_report_ref=None, open_reasons=None, client_ts=None
):
	reasons = json.loads(open_reasons) if isinstance(open_reasons, str) and open_reasons else open_reasons
	doc, rejected = _run(
		outbreaks.end_outbreak,
		outbreaks.DOCTYPE,
		outbreak,
		client_ts,
		outbreak,
		summary=summary,
		end_date=end_date or None,
		external_report_ref=external_report_ref,
		open_reasons=reasons or {},
	)
	return rejected or _detail(doc)


@frappe.whitelist(methods=["POST"])
@idempotent
def cancel_outbreak(outbreak=None, reason=None, client_ts=None):
	doc, rejected = _run(outbreaks.cancel_outbreak, outbreaks.DOCTYPE, outbreak, client_ts, outbreak, reason)
	return rejected or {"ok": True, "cancelled": cint(doc.docstatus) == 2}


@frappe.whitelist(methods=["POST"])
@idempotent
def dismiss_alert(alert=None, reason=None, client_ts=None):
	doc, rejected = _run(clusters.dismiss, clusters.ALERT_DOCTYPE, alert, client_ts, alert, reason)
	return rejected or {"ok": True, "alert": doc.name, "status": doc.status}


# --- khai báo bệnh truyền nhiễm -----------------------------------------------------------------------------------

REPORT_KEYS = notifiable.LIST_FIELDS


def _report(doc):
	row = {key: doc.get(key) for key in REPORT_KEYS}
	row["state"] = notifiable.state_of({**row, "docstatus": doc.docstatus})
	return row


@frappe.whitelist(methods=["POST"])
@idempotent
def create_report(
	department=None,
	patient_code=None,
	disease=None,
	diagnosed_on=None,
	birth_year=None,
	sex=None,
	outbreak_investigation=None,
	notes=None,
	client_ts=None,
):
	require_any_role(*notifiable.WRITE_ROLES)
	values = {
		"department": department or None,
		"patient_code": patient_code,
		"disease": disease or None,
		"diagnosed_on": _date(diagnosed_on),
		"birth_year": birth_year,
		"sex": sex,
		"outbreak_investigation": outbreak_investigation or None,
		"notes": notes,
	}
	doc, rejected = _run(notifiable.create_report, notifiable.DOCTYPE, department, client_ts, values)
	return rejected or {"ok": True, "report": _report(doc), "warnings": doc.flags.tc_warnings or []}


@frappe.whitelist(methods=["POST"])
@idempotent
def record_reported(report=None, reported_on=None, report_ref=None, client_ts=None):
	require_any_role(*notifiable.WRITE_ROLES)
	doc, rejected = _run(
		notifiable.record_reported,
		notifiable.DOCTYPE,
		report,
		client_ts,
		report,
		_date(reported_on),
		report_ref,
	)
	return rejected or {"ok": True, "report": _report(doc), "warnings": doc.flags.tc_warnings or []}


@frappe.whitelist(methods=["POST"])
@idempotent
def cancel_report(report=None, reason=None, client_ts=None):
	doc, rejected = _run(notifiable.cancel_report, notifiable.DOCTYPE, report, client_ts, report, reason)
	return rejected or {"ok": True, "report": _report(doc)}


@frappe.whitelist(methods=["GET"])
def portal_context():
	"""Dữ liệu Cổng khoa `/ksnk-khoa/khai-bao` (SCR-61 DEPT)."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Sign in to record notifiable disease reports."))
	require_any_role(*notifiable.WRITE_ROLES)
	allowed = permissions.allowed_departments()
	departments = _departments(allowed)
	scope = [row["name"] for row in departments] if allowed is not None else None
	return {
		"ok": True,
		"departments": departments,
		"reports": notifiable.list_reports(scope),
		"diseases": notifiable.diseases(),
		"missing_groups": notifiable.missing_groups(),
	}
