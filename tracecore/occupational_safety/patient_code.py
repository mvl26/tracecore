"""Mã người bệnh nguồn phơi nhiễm (FEAT-071; ADR-010 mở rộng; NFR-PRIV-01; A-137 Q2, k).

Bộ ba `source_patient_code` (Password, mã hóa trong `__Auth`) / `_masked` (`***` + 4 ký tự cuối) / `_hash` (HMAC,
`core.crypto`). Xem đầy đủ chỉ R01/R11, bắt buộc lý do, ghi Audit Log `View Patient Code` (không ghi mã). Cách che,
nhận dạng giá trị dấu sao và kiểm lý do dùng chung `core.patient_code` (A-136 Q7); tên trường khác nên giữ `apply`,
`reveal` riêng.
"""

import frappe
from frappe import _
from frappe.utils.password import remove_encrypted_password

from tracecore.core import audit, crypto
from tracecore.core import patient_code as shared

FIELD = "source_patient_code"
REVEAL_ROLES = shared.REVEAL_ROLES


def mask(code):
	return shared.mask(code) or None


def _is_dummy(value):
	return shared.is_placeholder(value)


def apply(doc):
	"""validate: nguồn đã biết + mã mới → chuẩn hóa, che, hash; nguồn chưa biết → bỏ cả ba trường."""
	value = doc.get(FIELD)
	if doc.source_known != "Yes":
		if doc.source_patient_code_hash and not doc.is_new():
			remove_encrypted_password(doc.doctype, doc.name, FIELD)
		doc.set(FIELD, None)
		doc.source_patient_code_masked = doc.source_patient_code_hash = None
		return
	if _is_dummy(value):
		return
	if not crypto.normalise_patient_code(value):
		# ô mã bị xóa trên Desk: Frappe xóa bản mã hóa, bỏ luôn bản che và hash để không còn "***1234" mồ côi
		doc.set(FIELD, None)
		doc.source_patient_code_masked = doc.source_patient_code_hash = None
		return
	code = crypto.normalise_patient_code(value)
	doc.set(FIELD, code)
	doc.source_patient_code_masked = mask(code)
	doc.source_patient_code_hash = crypto.patient_hash(code)


def reveal(doctype, name, reason):
	"""Mã đầy đủ cho R01/R11 có lý do; ghi Audit Log, không ghi mã."""
	# như core.patient_code: không cấp cho System Manager/Administrator (quản trị IT, NFR-PRIV-01)
	if not set(frappe.get_roles()) & set(REVEAL_ROLES):
		raise frappe.PermissionError(
			_("Only the head of infection control or a supervisor can view the full code.")
		)
	reason = shared._reason(reason)
	doc = frappe.get_doc(doctype, name)
	code = doc.get_password(FIELD, raise_exception=False) if doc.source_patient_code_hash else None
	audit.log("View Patient Code", doctype, name, reason=reason)
	return code
