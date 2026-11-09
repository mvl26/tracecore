"""Mã người bệnh của DocType KSNK toàn viện (M13, M14, M16) — ADR-010 mở rộng, NFR-PRIV-01, BRU-HAI-005; A-136 Q7.

Bộ ba trường trên DocType: ``patient_code`` (Password — Frappe mã hóa trong ``__Auth``, không vào Audit Log),
``patient_code_hash`` (HMAC-SHA256 của `core.crypto`, để tìm người bệnh tái xuất hiện mà không giải mã) và
``patient_code_masked`` (``***`` + 4 ký tự cuối, theo ux-foundations v1.12 — lưu sẵn để danh sách, báo cáo, file xuất
không phải giải mã). Xem mã đầy đủ chỉ R01/R11, bắt buộc lý do, ghi Audit Log ``View Patient Code`` (không chứa mã).

`Usage Record` (M2, FEAT-027) giữ cách che 4 ký tự giữa của FR-M2-17.1.
"""

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

from tracecore.core import audit, crypto
from tracecore.core.errors import Block, BlockedError

FIELD = "patient_code"
VISIBLE = 4
MASK = "***"
MAX_REASON = 140
REVEAL_ROLES = ("TC R01", "TC R11", "System Manager")


def normalise(code) -> str:
	return crypto.normalise_patient_code(code)


def mask(code) -> str:
	"""``***`` + 4 ký tự cuối của mã đã chuẩn hóa; mã không dài hơn 4 ký tự → chỉ ``***``; rỗng → chuỗi rỗng."""
	text = normalise(code)
	if not text:
		return ""
	return MASK + text[-VISIBLE:] if len(text) > VISIBLE else MASK


def hash_of(code) -> str | None:
	return crypto.patient_hash(code)


def is_placeholder(value) -> bool:
	"""Giá trị Password đọc lại từ DB là chuỗi dấu sao, không phải mã mới nhập."""
	return bool(value) and set(str(value)) == {"*"}


def apply(doc) -> None:
	"""Gọi ở ``validate``: mã vừa nhập (còn ở dạng rõ) → chuẩn hóa, điền hash và bản che; mã cũ (dấu sao) giữ nguyên."""
	value = doc.get(FIELD)
	if not value or is_placeholder(value):
		return
	text = normalise(value)
	doc.set(FIELD, text)
	doc.patient_code_hash = hash_of(text)
	doc.patient_code_masked = mask(text)


def _reason(reason) -> str:
	text = " ".join(str(reason or "").split())
	if not text or len(text) > MAX_REASON:
		raise BlockedError(
			Block(
				"REASON_REQUIRED",
				_("Reason is required"),
				_("A reason of 1 to {0} characters is required to view the patient code.").format(MAX_REASON),
				_("Enter why you need the full patient code."),
			)
		)
	return text


def reveal(doctype: str, name: str, reason) -> str:
	"""Mã người bệnh đầy đủ cho R01/R11 có quyền đọc chứng từ; lý do bắt buộc; Audit ``View Patient Code``."""
	if not set(frappe.get_roles()) & set(REVEAL_ROLES):
		raise frappe.PermissionError(_("Only infection control staff can view the full patient code."))
	text = _reason(reason)
	if not frappe.db.exists("DocType", doctype) or frappe.get_meta(doctype).get_field(FIELD) is None:
		raise frappe.PermissionError(_("{0} has no patient code.").format(_(doctype)))
	if frappe.get_meta(doctype).get_field(FIELD).fieldtype != "Password":
		raise frappe.PermissionError(_("{0} has no patient code.").format(_(doctype)))
	if not frappe.db.exists(doctype, name):
		raise frappe.DoesNotExistError(_("{0} {1} does not exist.").format(_(doctype), name))
	if not frappe.has_permission(doctype, "read", name):
		raise frappe.PermissionError(_("You are not allowed to read {0} {1}.").format(_(doctype), name))
	code = get_decrypted_password(doctype, name, FIELD, raise_exception=False) or ""
	audit.log("View Patient Code", doctype, name, reason=text)
	return code
