"""Mã người bệnh nguồn phơi nhiễm (FEAT-071; ADR-010 mở rộng; NFR-PRIV-01; A-137 Q2, k).

Bộ ba `source_patient_code` (Password, mã hóa trong `__Auth`) / `_masked` (`***` + 4 ký tự cuối) / `_hash` (HMAC,
`core.crypto`). Xem đầy đủ chỉ R01/R11, bắt buộc lý do, ghi Audit Log `View Patient Code` (không ghi mã). Chuyển sang
`core.patient_code` khi module dùng chung có (FEAT-063).
"""

import frappe
from frappe import _
from frappe.utils import cstr
from frappe.utils.password import remove_encrypted_password

from tracecore.core import audit, crypto
from tracecore.core.errors import Block, BlockedError

FIELD = "source_patient_code"
REVEAL_ROLES = ("TC R01", "TC R11")


def mask(code):
	text = crypto.normalise_patient_code(code)
	return f"***{text[-4:]}" if text else None


def _is_dummy(value):
	return bool(value) and set(cstr(value)) == {"*"}


def apply(doc):
	"""validate: nguồn đã biết + mã mới → chuẩn hóa, che, hash; nguồn chưa biết → bỏ cả ba trường."""
	value = doc.get(FIELD)
	if doc.source_known != "Yes":
		if doc.source_patient_code_hash and not doc.is_new():
			remove_encrypted_password(doc.doctype, doc.name, FIELD)
		doc.set(FIELD, None)
		doc.source_patient_code_masked = doc.source_patient_code_hash = None
		return
	if not value or _is_dummy(value):
		return
	code = crypto.normalise_patient_code(value)
	doc.set(FIELD, code)
	doc.source_patient_code_masked = mask(code)
	doc.source_patient_code_hash = crypto.patient_hash(code)


def reveal(doctype, name, reason):
	"""Mã đầy đủ cho R01/R11 có lý do; ghi Audit Log, không ghi mã."""
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(REVEAL_ROLES):
		raise frappe.PermissionError(_("Only the head of infection control or a supervisor can view the full code."))
	reason = cstr(reason).strip()
	if not reason:
		raise BlockedError(
			Block(
				"REASON_REQUIRED",
				_("Reason is required"),
				_("Viewing the full patient code needs a reason."),
				_("Enter the reason, then view again."),
			)
		)
	doc = frappe.get_doc(doctype, name)
	code = doc.get_password(FIELD, raise_exception=False) if doc.source_patient_code_hash else None
	audit.log("View Patient Code", doctype, name, reason=reason)
	return code
