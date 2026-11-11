"""Sổ văn bản nội bộ KSNK (FEAT-058; FR-M11-07, FR-M11-07.1, FR-M11-07.2; BRU-ICP-005; A-133 Q4).

- ``review_due`` mặc định = ``issued_on`` + ``IC Program Settings.doc_review_months`` (mặc định 12 tháng).
- Trạng thái: Hiệu lực / Cần rà soát / Thay thế. Scheduler chuyển "Cần rà soát" và báo R01 (``reminders``); R01 lùi
  hạn rà soát quá mốc 30 ngày thì văn bản về "Hiệu lực". Ban hành bản mới có ``supersedes`` → bản cũ "Thay thế",
  ``superseded_by`` trỏ bản mới; lịch sử giữ nguyên, không xóa (Audit Log, ``block_delete``).
- Hàm tính chỉ số ``ic_procedure_documents_current`` (hook ``tracecore_ic_indicators``): văn bản Thay thế và văn bản
  quá hạn rà soát không vào tử số.
"""

import calendar
from urllib.parse import quote  # FEAT-073

import frappe
from frappe import _
from frappe.utils import add_months, cint, getdate

from tracecore.core import audit, qr  # FEAT-073
from tracecore.core.errors import Block, BlockedError  # FEAT-073
from tracecore.infection_program import reminders

DOCTYPE = "IC Procedure Document"
SETTINGS = "IC Program Settings"
DEFAULT_REVIEW_MONTHS = 12
INDICATOR_METHOD = "ic_procedure_documents_current"


def _review_months():
	return cint(frappe.db.get_single_value(SETTINGS, "doc_review_months")) or DEFAULT_REVIEW_MONTHS


def validate(doc):
	if not doc.review_due and doc.issued_on:
		doc.review_due = add_months(getdate(doc.issued_on), _review_months())
	if doc.review_due and doc.issued_on and getdate(doc.review_due) < getdate(doc.issued_on):
		frappe.throw(_("Review due date cannot be before the issue date."))
	if cint(doc.version_no) < 1:
		frappe.throw(_("Version must be 1 or higher."))
	if doc.supersedes:
		_check_supersedes(doc)
	_set_status(doc)


def _check_supersedes(doc):
	if doc.supersedes == doc.name:
		frappe.throw(_("A document cannot supersede itself."))
	old = frappe.db.get_value(
		DOCTYPE, doc.supersedes, ["doc_code", "version_no", "superseded_by"], as_dict=True
	)
	if old.doc_code != doc.doc_code:
		frappe.throw(
			_("The new version must keep the document code {0} of {1}.").format(old.doc_code, doc.supersedes)
		)
	if cint(doc.version_no) <= cint(old.version_no):
		frappe.throw(
			_("The new version must be higher than version {0} of {1}.").format(
				old.version_no, doc.supersedes
			)
		)
	if old.superseded_by and old.superseded_by != doc.name:
		frappe.throw(_("{0} is already superseded by {1}.").format(doc.supersedes, old.superseded_by))


def _set_status(doc):
	if doc.superseded_by:
		doc.status = reminders.SUPERSEDED
	elif doc.status in (DRAFT, WITHDRAWN):  # FEAT-073 (A-151 Q3): chỉ publish/withdraw đổi hai trạng thái này
		return
	elif doc.flags.keep_status:
		return  # scheduler vừa chuyển "Cần rà soát"
	elif doc.status == reminders.REVIEW_NEEDED and not reminders.review_needed(doc.review_due):
		doc.status = reminders.EFFECTIVE  # R01 rà soát xong, lùi hạn
	elif not doc.status:
		doc.status = reminders.EFFECTIVE


def on_update(doc):
	"""Ban hành bản mới → bản cũ "Thay thế" (FR-M11-07, FR-M11-07.2)."""
	if not doc.supersedes or doc.status == DRAFT:  # FEAT-073: bản Nháp chưa thay bản đang hiện hành
		return
	old = frappe.get_doc(DOCTYPE, doc.supersedes)
	if old.superseded_by == doc.name and old.status == reminders.SUPERSEDED:
		return
	old.superseded_by = doc.name
	old.status = reminders.SUPERSEDED
	old.flags.ignore_permissions = True
	old.save()


# --- chỉ số M9 (FR-M11-07.1, BRU-ICP-005) ------------------------------------------------------------------------


def _period_end(period):
	year, month = (int(part) for part in period.split("-"))
	return getdate(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}")


def current_documents(period, department=None):
	"""(tử số, mẫu số, cỡ mẫu) cho kỳ ``YYYY-MM``; chỉ tính toàn viện (văn bản không thuộc khoa)."""
	if department:
		return 0, 0, 0
	end = _period_end(period)
	rows = frappe.get_all(
		DOCTYPE,
		# FEAT-073: bản Nháp chưa ban hành và bản đã thu hồi không là văn bản đang dùng
		filters={"issued_on": ["<=", end], "status": ["not in", [DRAFT, WITHDRAWN]]},
		fields=["name", "review_due", "superseded_by"],
	)
	successors = {
		row.name: row.issued_on
		for row in frappe.get_all(
			DOCTYPE,
			filters={"name": ["in", [r.superseded_by for r in rows if r.superseded_by] or [""]]},
			fields=["name", "issued_on"],
		)
	}
	current = [
		row
		for row in rows
		if not row.superseded_by or getdate(successors.get(row.superseded_by) or end) > end
	]
	updated = [row for row in current if row.review_due and getdate(row.review_due) >= end]
	return len(updated), len(current), len(current)


def register():
	"""Hook ``tracecore_ic_indicators``."""
	return {INDICATOR_METHOD: current_documents}


# --- FEAT-073 (A-151 Q3; FR-M17-06, FR-M17-06.1; UC-56 bước 6, E4): tài liệu truyền thông có QR ---------------------
# QR = URL cố định ``/tai-lieu/<doc_code>`` nên in một lần, bản mới cùng mã tự được trỏ tới. Bản Nháp chưa hoạt động;
# R01 ban hành (Nháp → Hiệu lực, thay bản cũ) hoặc thu hồi có lý do (Audit Log).

DRAFT, WITHDRAWN = "Draft", "Withdrawn"
MATERIAL_TYPE = "Communication Material"
PUBLIC_ROUTE = "tai-lieu"
CURRENT_STATUSES = (reminders.EFFECTIVE, reminders.REVIEW_NEEDED)
PUBLISHER_ROLES = frozenset({"TC R01", "System Manager"})


def can_publish(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & PUBLISHER_ROLES)


def _require_publisher():
	if not can_publish():
		frappe.throw(
			_("Only the head of infection control can issue or withdraw a document."), frappe.PermissionError
		)


def _material_blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def publish(name):
	"""R01 ban hành bản Nháp: Hiệu lực, ngày ban hành mặc định hôm nay; bản trước (``supersedes``) thành Thay thế."""
	_require_publisher()
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status != DRAFT:
		raise _material_blocked(
			"DOCUMENT_NOT_DRAFT",
			_("Document already issued"),
			_("Document {0} is {1}, not a draft.").format(name, _(doc.status)),
			_("Create a new version to change an issued document."),
		)
	doc.status = reminders.EFFECTIVE
	doc.issued_on = doc.issued_on or getdate()
	doc.review_due = None
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def withdraw(name, reason):
	"""R01 thu hồi bản đang hiện hành: bắt buộc lý do, Audit Log; QR trỏ tới trang "Tài liệu đã thu hồi"."""
	_require_publisher()
	reason = (reason or "").strip()
	if not reason:
		raise _material_blocked(
			"REASON_REQUIRED",
			_("Reason required"),
			_("No reason was given for withdrawing the document."),
			_("Enter why the document is withdrawn."),
		)
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status not in CURRENT_STATUSES:
		raise _material_blocked(
			"DOCUMENT_NOT_CURRENT",
			_("Document not in use"),
			_("Document {0} is {1}; only a document in use can be withdrawn.").format(name, _(doc.status)),
			_("Open the current version of the document."),
		)
	old = doc.status
	doc.db_set({"status": WITHDRAWN, "withdrawn_reason": reason})
	audit.log("Update", DOCTYPE, name, old={"status": old}, new={"status": WITHDRAWN}, reason=reason)
	return doc.name


def current_material(doc_code):
	"""Bản hiện hành của tài liệu truyền thông ``doc_code``: {state current/draft/withdrawn/missing, ...}."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={"doc_code": doc_code, "doc_type": MATERIAL_TYPE},
		fields=["name", "doc_code", "title", "version_no", "status", "issued_on", "file"],
		order_by="version_no desc, creation desc",
	)
	current = next((row for row in rows if row.status in CURRENT_STATUSES), None)
	if current:
		return {"state": "current", **current}
	statuses = {row.status for row in rows}
	state = "withdrawn" if WITHDRAWN in statuses else "draft" if DRAFT in statuses else "missing"
	latest = rows[0] if rows else {}
	return {"state": state, "doc_code": doc_code, "title": latest.get("title"), "name": latest.get("name")}


def material_url(doc_code):
	return frappe.utils.get_url(f"/{PUBLIC_ROUTE}/{quote(doc_code, safe='')}")


def material_qr_png(doc_code):
	return qr.qr_png(material_url(doc_code), module_px=6, margin_px=24)
