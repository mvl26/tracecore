"""Cấu hình chuyên môn M16 có phiên bản: mẫu theo dõi sau phơi nhiễm, yêu cầu tiêm chủng (FEAT-071; FR-M16-04,
FR-M16-07; BRU-OCC-004; NFR-MAINT-04; A-137 Q3).

Mẫu theo dõi: mỗi loại phơi nhiễm nhiều phiên bản `{loại}-V{n}`, Draft → Approved → Superseded; mỗi loại tối đa một
bản Approved; bản đã duyệt không sửa được (sửa = tạo phiên bản mới). Nội dung do R01 nhập — fixtures chỉ chèn bản Nháp
rỗng khi chưa có, không ghi đè bản bệnh viện đã sửa.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core import audit

TEMPLATE = "Exposure Follow-up Template"
REQUIREMENT = "Immunization Requirement"
EXPOSURE_TYPES = (
	"Needlestick or Sharps",
	"Mucous Membrane Splash",
	"Non-intact Skin",
	"Respiratory",
	"Other",
)
APPROVER_ROLES = ("TC R01", "System Manager")
# Vaccine mẫu (Nháp, chưa có số mũi): R01 bổ sung số mũi, khoảng cách và nhóm nguy cơ rồi duyệt
DEFAULT_VACCINES = ("Hepatitis B", "Influenza")
FROZEN_FIELDS = ("exposure_type",)


def _require_approver():
	user = frappe.session.user
	if user != "Administrator" and not set(frappe.get_roles(user)) & set(APPROVER_ROLES):
		raise frappe.PermissionError(_("Only the head of infection control can approve this."))


# --- mẫu theo dõi --------------------------------------------------------------------------------------------------


def before_insert_template(doc):
	latest = frappe.db.get_value(TEMPLATE, {"exposure_type": doc.exposure_type}, "max(version_no)")
	doc.version_no = cint(latest) + 1
	doc.status = "Draft"
	doc.approved_by = doc.approved_on = None


def validate_template(doc):
	for row in doc.steps:
		row.step = (row.step or "").strip()
	if doc.is_new() or doc.flags.get("tc_status_change"):
		return
	before = doc.get_doc_before_save()
	if before and before.status != "Draft" and _steps(before) != _steps(doc):
		frappe.throw(
			_("An approved follow-up template cannot be changed. Create a new version instead."),
			frappe.ValidationError,
		)


def _steps(doc):
	return [(row.step, cint(row.days_after)) for row in doc.steps]


def approve_template(name):
	"""R01 duyệt một phiên bản: cần ≥ 1 bước; bản Approved cũ cùng loại → Superseded."""
	_require_approver()
	doc = frappe.get_doc(TEMPLATE, name)
	if doc.status != "Draft":
		frappe.throw(_("Only a draft version can be approved."), frappe.ValidationError)
	if not doc.steps:
		frappe.throw(_("Add at least one follow-up step before approving."), frappe.ValidationError)
	for old in frappe.get_all(
		TEMPLATE, filters={"exposure_type": doc.exposure_type, "status": "Approved"}, pluck="name"
	):
		_set_status(frappe.get_doc(TEMPLATE, old), "Superseded")
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	_set_status(doc, "Approved")
	return doc


def _set_status(doc, status):
	old = doc.status
	doc.status = status
	doc.flags.tc_status_change = True
	doc.save(ignore_permissions=True)
	audit.log("Update", doc.doctype, doc.name, old={"status": old}, new={"status": status}, reason=_(status))


def active_template(exposure_type):
	name = frappe.db.get_value(TEMPLATE, {"exposure_type": exposure_type, "status": "Approved"}, "name")
	return frappe.get_doc(TEMPLATE, name) if name else None


# --- yêu cầu tiêm chủng --------------------------------------------------------------------------------------------


def validate_requirement(doc):
	doc.vaccine = (doc.vaccine or "").strip()
	if doc.status == "Approved" and cint(doc.doses_required) < 1:
		frappe.throw(_("An approved vaccine requirement needs at least one dose."), frappe.ValidationError)


def approve_requirement(name):
	_require_approver()
	doc = frappe.get_doc(REQUIREMENT, name)
	if cint(doc.doses_required) < 1:
		frappe.throw(_("Enter the number of doses before approving."), frappe.ValidationError)
	old = doc.status
	doc.status = "Approved"
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.save(ignore_permissions=True)
	audit.log(
		"Update", REQUIREMENT, doc.name, old={"status": old}, new={"status": "Approved"}, reason=_("Approved")
	)
	return doc


def approved_requirements():
	return [
		frappe.get_doc(REQUIREMENT, name)
		for name in frappe.get_all(REQUIREMENT, {"status": "Approved"}, pluck="name")
	]


# --- fixtures Nháp (after_migrate) ---------------------------------------------------------------------------------


def ensure_default_config():
	"""Chèn mẫu theo dõi Nháp rỗng cho loại chưa có mẫu nào và vaccine mẫu chưa có; không ghi đè (NFR-MAINT-04)."""
	for exposure_type in EXPOSURE_TYPES:
		if frappe.db.exists(TEMPLATE, {"exposure_type": exposure_type}):
			continue
		frappe.get_doc({"doctype": TEMPLATE, "exposure_type": exposure_type}).insert(ignore_permissions=True)
	for vaccine in DEFAULT_VACCINES:
		label = _(vaccine, "vi")
		if frappe.db.exists(REQUIREMENT, label):
			continue
		frappe.get_doc({"doctype": REQUIREMENT, "vaccine": label}).insert(ignore_permissions=True)
