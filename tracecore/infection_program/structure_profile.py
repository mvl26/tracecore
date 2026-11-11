"""Bộ tiêu chí cơ cấu KSNK có phiên bản ``IC Structure Profile`` (FEAT-094; FR-M11-01.8; NFR-MAINT-04; A-138 a, A-143).

Vòng đời Nháp → Đã duyệt → Thay thế. Chỉ R01 duyệt (``approve``); bản đã duyệt không sửa được (sửa = tạo bản mới).
``active_profile`` trả bản Đã duyệt có ``effective_from`` ≤ ngày cần tính mới nhất; không có → ``None`` và
``structure.compute`` chỉ kiểm phần đếm (OQ-V12-16). Tiêu chí chuyên môn là dữ liệu của bản ghi, không nằm trong code.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, today

from tracecore.core import audit

PROFILE = "IC Structure Profile"
DRAFT, APPROVED, SUPERSEDED = "Draft", "Approved", "Superseded"
APPROVER_ROLES = ("TC R01", "System Manager")
REPRESENTING, ROLE = "Representing", "Role"
ROLE_CONTEXT = "IC Structure Role Requirement"


def before_insert(doc):
	latest = frappe.db.get_value(PROFILE, {}, "max(version_no)")
	doc.version_no = cint(latest) + 1
	doc.status = DRAFT
	doc.approved_by = doc.approved_by_name = doc.approved_on = None


def _content(doc):
	"""Phần tiêu chí của một bản (để so khi bản không còn Nháp)."""
	meta = frappe.get_meta(PROFILE)
	skip = {"status", "approved_by", "approved_by_name", "approved_on", "version_no"}
	values = {
		df.fieldname: doc.get(df.fieldname)
		for df in meta.fields
		if df.fieldtype not in ("Section Break", "Column Break", "Table") and df.fieldname not in skip
	}
	for table in ("committee_requirements", "role_requirements"):
		child = frappe.get_meta(meta.get_field(table).options)
		values[table] = [
			tuple(row.get(df.fieldname) for df in child.fields if df.fieldtype not in ("Section Break",))
			for row in doc.get(table) or []
		]
	return values


def _validate_rows(doc):
	for row in doc.committee_requirements:
		if row.requirement_type == REPRESENTING and not row.representing:
			frappe.throw(_("Row {0}: choose the group the committee must include.").format(row.idx))
		if row.requirement_type == ROLE and not row.committee_role:
			frappe.throw(_("Row {0}: choose the committee role.").format(row.idx))
		if cint(row.min_count) < 1:
			frappe.throw(_("Row {0}: the minimum count must be at least 1.").format(row.idx))
	seen = set()
	for row in doc.role_requirements:
		key = (row.ic_role, row.applies_to)
		if key in seen:
			frappe.throw(
				_("Role {0} for {1} is listed more than once.").format(
					_(row.ic_role, context=ROLE_CONTEXT), _(row.applies_to, context=ROLE_CONTEXT)
				)
			)
		seen.add(key)
		row.certificate_types = "\n".join(
			line.strip() for line in (row.certificate_types or "").splitlines() if line.strip()
		)


def validate(doc):
	if cint(doc.department_min_beds) < 1:
		frappe.throw(_("The number of beds requiring an IC department must be at least 1."))
	_validate_rows(doc)
	if doc.is_new() or doc.flags.get("tc_status_change"):
		return
	before = doc.get_doc_before_save()
	if before and before.status != DRAFT and _content(before) != _content(doc):
		frappe.throw(
			_("An approved structure profile cannot be changed. Create a new version instead."),
			frappe.ValidationError,
		)


def _require_approver():
	user = frappe.session.user
	if user != "Administrator" and not set(frappe.get_roles(user)) & set(APPROVER_ROLES):
		raise frappe.PermissionError(_("Only the head of infection control can approve this."))


def _set_status(doc, status):
	old = doc.status
	doc.status = status
	doc.flags.tc_status_change = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		doc.flags.tc_status_change = False
	audit.log("Update", PROFILE, doc.name, old={"status": old}, new={"status": status}, reason=_(status))


def approve(name):
	"""R01 duyệt bản Nháp (AC-094-01); bản Đã duyệt cũ có hiệu lực không muộn hơn bản mới → Thay thế."""
	_require_approver()
	doc = frappe.get_doc(PROFILE, name)
	if doc.status != DRAFT:
		frappe.throw(_("Only a draft version can be approved."), frappe.ValidationError)
	if getdate(doc.effective_from) <= getdate(today()):
		for old in frappe.get_all(
			PROFILE,
			filters={
				"status": APPROVED,
				"name": ["!=", doc.name],
				"effective_from": ["<=", doc.effective_from],
			},
			pluck="name",
		):
			_set_status(frappe.get_doc(PROFILE, old), SUPERSEDED)
	doc.approved_by = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
	doc.approved_on = now_datetime()
	_set_status(doc, APPROVED)
	return doc


def active_profile(on=None):
	"""Bản Đã duyệt có hiệu lực tại ngày ``on`` (mới nhất theo ``effective_from`` rồi ``version_no``); None nếu chưa có."""
	rows = frappe.get_all(
		PROFILE,
		filters={"status": APPROVED, "effective_from": ["<=", on or today()]},
		pluck="name",
		order_by="effective_from desc, version_no desc",
		limit=1,
	)
	return frappe.get_doc(PROFILE, rows[0]) if rows else None


def field_default(fieldname):
	"""Giá trị mặc định của trường trong DocType — dùng khi chưa có bản Đã duyệt (chỉ kiểm phần đếm)."""
	return frappe.get_meta(PROFILE).get_field(fieldname).default
