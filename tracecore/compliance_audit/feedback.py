"""Phản hồi khoa và đề nghị NC khi phiếu giám sát ghi sổ (FEAT-060; FR-M12-08, FR-M12-09, BRU-AUD-005, A-132 d).

Người nhận phản hồi: người dùng có `TC R08` (trưởng khoa) hoặc `TC R12` (mạng lưới viên) và User Permission Department
= khoa của phiếu. Khoa không có R12 nào → gửi thêm R01 (UC-45 A1). Không đọc DocType M11 (`IC Network Member`).
Mục trọng yếu không đạt → ``AUDIT_CRITICAL_FAIL`` cho R01/R11 (theo Rule) để quyết định Mở NC / Bỏ qua (``nc``).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from tracecore.compliance_audit import scoring
from tracecore.core import notification

R01, R08, R12 = "TC R01", "TC R08", "TC R12"


def _department_users(department, role):
	permitted = set(
		frappe.get_all(
			"User Permission", filters={"allow": "Department", "for_value": department}, pluck="user"
		)
	)
	if not permitted:
		return []
	holders = frappe.get_all(
		"Has Role", filters={"role": role, "parenttype": "User", "parent": ["in", list(permitted)]}, pluck="parent"
	)
	return sorted(
		frappe.get_all("User", filters={"name": ["in", holders or [""]], "enabled": 1}, pluck="name")
	)


def failed_items(doc):
	return [row for row in doc.answers or () if row.answer == scoring.FAIL]


def summary(doc):
	"""Một dòng kết quả cho thông báo: điểm, kết quả, mục không đạt."""
	score = _("not scored") if doc.score_pct in (None, "") else f"{flt(doc.score_pct, 1):g} %"
	result = _(doc.result) if doc.result else _("No result")
	parts = [_("Score {0}, result {1}.").format(score, result)]
	failed = failed_items(doc)
	if failed:
		parts.append(
			_("Failed items: {0}.").format(
				"; ".join(
					f"{row.item_code}{' (' + _('critical') + ')' if cint(row.is_critical) else ''}: {row.question}"
					for row in failed
				)
			)
		)
	if doc.opportunities:
		parts.append(_("Opportunities observed: {0}.").format(len(doc.opportunities)))
	return " ".join(parts)


def after_submit(doc):
	"""Gọi từ ``sessions.on_submit``."""
	heads = _department_users(doc.department, R08)
	members = _department_users(doc.department, R12)
	users = heads + members
	if not members:
		users += sorted(notification._users_with_role(R01))
	title = doc.template_title or doc.template_code
	notification.emit(
		"AUDIT_FEEDBACK",
		doc,
		subject=_("Audit result {0}: {1}").format(doc.name, title),
		message=summary(doc),
		users=list(dict.fromkeys(users)),
	)
	if cint(doc.critical_failed):
		notification.emit(
			"AUDIT_CRITICAL_FAIL",
			doc,
			subject=_("Critical item failed in audit {0} ({1})").format(doc.name, doc.department),
			message=summary(doc) + " " + _("Open a non-conformance or dismiss it with a reason."),
		)
