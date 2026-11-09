"""Đề nghị mở NC loại Compliance từ phiếu có mục trọng yếu không đạt (FEAT-060; FR-M12-09, BRU-AUD-005, A-132 c).

Ghi sổ phiếu chỉ đặt ``nc_status = Suggested``; R01/R11 quyết định ``open_nc`` (tạo `Incident CAPA` qua hook
``tracecore_compliance_nc`` do M2 cài — M12 không import M2) hoặc ``dismiss_nc`` có lý do (Audit Log).
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr

from tracecore.compliance_audit import feedback
from tracecore.compliance_audit.sessions import blocked
from tracecore.core import audit, extension

DOCTYPE = "Audit Session"
HOOK = "tracecore_compliance_nc"
SUGGESTED, OPENED, DISMISSED = "Suggested", "Opened", "Dismissed"
NC_ROLES = frozenset({"TC R01", "TC R11", "System Manager"})
BADGE_SLUG = "tuan-thu"


def can_decide(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & NC_ROLES)


def _require_decider():
	if not can_decide():
		frappe.throw(
			_("Only R01 or R11 can open or dismiss a non-conformance from an audit."), frappe.PermissionError
		)


def _suggested(name):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	if doc.docstatus != 1 or doc.nc_status not in (SUGGESTED, OPENED):
		raise blocked(
			"AUDIT_NC_NOT_SUGGESTED",
			_("No non-conformance to open"),
			_("Audit {0} has no failed critical item waiting for a decision.").format(name),
			_("Open a non-conformance from the incident screen if it is still needed."),
		)
	return doc


def open_nc(name):
	"""Tạo (hoặc trả) Incident Compliance liên kết phiếu nguồn; trả tên Incident."""
	_require_decider()
	doc = _suggested(name)
	if doc.nc_status == OPENED and doc.nc_name:
		return doc.nc_name
	failed = [row for row in feedback.failed_items(doc) if cint(row.is_critical)]
	description = _("Audit {0} ({1}, {2}): critical items failed: {3}").format(
		doc.name,
		doc.template_title or doc.template_code,
		frappe.format(doc.audit_date, "Date"),
		"; ".join(
			f"{row.item_code} {row.question}" + (f" ({row.note})" if row.note else "") for row in failed
		),
	)
	ctx = {"session": doc.name, "department": doc.department, "description": description}
	results = [result for result in extension.run(HOOK, ctx) if result]
	if not results:
		frappe.throw(_("No module handles non-conformances from audits."))
	doc.db_set({"nc_status": OPENED, "nc_name": results[0]})
	return results[0]


def dismiss_nc(name, reason):
	"""Bỏ qua đề nghị NC, bắt buộc lý do, ghi Audit Log."""
	_require_decider()
	reason = cstr(reason).strip()
	if not reason:
		raise blocked(
			"REASON_REQUIRED",
			_("Reason required"),
			_("No reason was given for not opening a non-conformance."),
			_("Enter why no non-conformance is needed."),
		)
	doc = _suggested(name)
	if doc.nc_status == OPENED:
		raise blocked(
			"AUDIT_NC_NOT_SUGGESTED",
			_("Non-conformance already opened"),
			_("Audit {0} already has incident {1}.").format(name, doc.nc_name),
			_("Follow the incident until it is closed."),
		)
	doc.db_set({"nc_status": DISMISSED, "nc_reason": reason})
	audit.log(
		"Update", DOCTYPE, name, old={"nc_status": SUGGESTED}, new={"nc_status": DISMISSED}, reason=reason
	)


def pending(limit=50):
	"""Phiếu đã ghi sổ đang chờ quyết định NC, mới nhất trước, kèm mục trọng yếu không đạt."""
	rows = frappe.get_list(
		DOCTYPE,
		filters={"docstatus": 1, "nc_status": SUGGESTED},
		fields=["name", "department", "template_title", "template_code", "audit_date", "score_pct", "result"],
		order_by="audit_date desc, creation desc",
		limit_page_length=limit,
	)
	for row in rows:
		row["failed_items"] = frappe.get_all(
			"Audit Answer",
			filters={"parent": row["name"], "parenttype": DOCTYPE, "answer": "Fail", "is_critical": 1},
			fields=["item_code", "question", "note"],
			order_by="idx asc",
		)
	return rows


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: số phiếu chờ quyết định NC trên mục Báo cáo tuân thủ (R01/R11)."""
	if not can_decide(user):
		return {}
	return {BADGE_SLUG: frappe.db.count(DOCTYPE, {"docstatus": 1, "nc_status": SUGGESTED})}
