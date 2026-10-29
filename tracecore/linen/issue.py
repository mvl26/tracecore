"""Cấp phát, cấp mới và hủy đồ vải theo khoa (FEAT-035, UC-18, FR-M3-05, .1, .2, FR-M3-06.2; BRU-LIN-001;
architecture §5.3 DT-LINENISS, A-50 G2, G4, G5, G8).

`Linen Issue.kind`: ``Return`` (trả sau giặt), ``New`` (cấp mới từ kho, UC-18 A1), ``Dispose`` (hủy, cần lý do và ảnh).
Cấp (``Return``/``New``) cần người nhận và chữ ký (thẻ hoặc cảm ứng) trước khi ghi sổ. Vượt định mức tối đa chỉ cảnh báo,
không chặn (FR-M3-05.2). Số chiếc ↔ kg quy đổi như thu gom (`collection.normalize_line`).
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, now_datetime

from tracecore.core import station_auth
from tracecore.core.errors import Block, BlockedError
from tracecore.linen import collection, reconcile

KINDS = reconcile.KINDS
SIGN_METHODS = ("Card", "Touch")
SIGNATURE_PREFIX = "data:image/png;base64,"
SIGNATURE_MAX_LENGTH = 200_000  # ảnh chữ ký PNG ≤ ~150 KB sau base64 (giống Issue Note)


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def validate(doc):
	"""Kiểm phiếu và điền giá trị suy ra. Chạy trước kiểm bắt buộc/liên kết của Frappe nên bỏ qua dòng thiếu loại hoặc loại
	không tồn tại để Frappe báo đúng lỗi."""
	if not doc.lines:
		frappe.throw(_("Add at least one line."))
	if doc.kind not in KINDS:
		frappe.throw(_("Kind {0} is not valid.").format(doc.kind or "-"))
	if not doc.issued_at:
		doc.issued_at = now_datetime()
	for row in doc.lines:
		info = collection._linen_type(row.linen_type) if row.linen_type else None
		if not info:
			continue
		if not info.is_active and doc.kind != reconcile.DISPOSE:
			frappe.throw(_("Row {0}: linen type {1} is no longer in use.").format(row.idx, row.linen_type))
		collection.normalize_line(row, info)
	collection.set_totals(doc)
	if doc.kind == reconcile.DISPOSE:
		_validate_dispose(doc)
	else:
		_fill_recipient(doc)
	doc.quota_warning = (
		reconcile.warning_text(reconcile.quota_warnings(doc.department, doc.kind, doc.lines)) or None
	)


def _validate_dispose(doc):
	"""Hủy cần lý do và ảnh (FR-M3-06.2); không có người nhận hay chữ ký."""
	if not cstr(doc.reason).strip():
		frappe.throw(_("Enter the reason for disposing of the linen."))
	if not doc.evidence:
		frappe.throw(_("Attach a photo of the linen to dispose of."))
	doc.recipient = doc.recipient_name = doc.sign_method = doc.signature = doc.signed_at = None


def _fill_recipient(doc):
	if doc.recipient:
		doc.recipient_name = frappe.db.get_value("Employee", doc.recipient, "employee_name")


def before_submit(doc):
	"""Cấp phát phải có người nhận và chữ ký (FR-M3-05.1)."""
	if doc.kind == reconcile.DISPOSE:
		return
	if not doc.recipient:
		frappe.throw(_("Choose the recipient before submitting."))
	if doc.sign_method not in SIGN_METHODS:
		frappe.throw(_("The recipient must sign with the card or on the screen."))
	if doc.sign_method == "Touch" and not doc.signature:
		frappe.throw(_("The recipient's signature is missing."))
	if not doc.signed_at:
		doc.signed_at = now_datetime()


# --- Màn trạm đồ vải (RPC tracecore.v1.linen.*) --------------------------------------------------------------


def _recipient(card):
	card = station_auth.normalize_card_id(card)
	row = (
		frappe.db.get_value(
			"Employee", {"tc_card_id": card}, ["name", "status", "tc_card_enabled"], as_dict=True
		)
		if card
		else None
	)
	if not row or row.status != "Active" or not cint(row.tc_card_enabled):
		raise _blocked(
			"LINEN_RECIPIENT_INVALID",
			_("Recipient card is not valid"),
			_("The card does not belong to an active employee."),
			_("Ask the recipient for an active employee card, or call R02."),
		)
	return row.name


def _signature(method, signature):
	if method not in SIGN_METHODS:
		raise _blocked(
			"LINEN_SIGNATURE_INVALID",
			_("Signature is not valid"),
			_("Sign method {0} is not supported.").format(method or "-"),
			_("Sign with the card or on the screen."),
		)
	if method == "Card":
		return None
	if (
		not isinstance(signature, str)
		or not signature.startswith(SIGNATURE_PREFIX)
		or len(signature) <= len(SIGNATURE_PREFIX)
		or len(signature) > SIGNATURE_MAX_LENGTH
	):
		raise _blocked(
			"LINEN_SIGNATURE_INVALID",
			_("Signature is not valid"),
			_("The signature drawn on the screen is empty or too large."),
			_("Clear the signature box and ask the recipient to sign again."),
		)
	return signature


def record(station, employee, department, kind, recipient_card, sign_method, signature, lines, note=None):
	"""Ghi sổ một lượt cấp phát từ trạm đồ vải: kiểm đầu vào bằng `Block` (mã LINEN_*), rồi tạo và ghi sổ `Linen Issue`.

	Trạm chỉ cấp (``Return``/``New``); hủy làm trên Desk vì cần ảnh. `employee` là người cấp (Employee của phiên thẻ).
	"""
	if kind not in (reconcile.RETURN, reconcile.NEW):
		raise _blocked(
			"LINEN_ISSUE_KIND_INVALID",
			_("Kind is not valid"),
			_("Kind {0} cannot be recorded at the station.").format(kind if isinstance(kind, str) else "-"),
			_("Choose Return or New."),
		)
	collection.check_department(department)
	rows = collection.prepare_rows(lines, note)
	for row in rows:
		row.pop("contaminated", None)
	recipient = _recipient(recipient_card)
	signature = _signature(sign_method, signature)
	doc = frappe.get_doc(
		{
			"doctype": "Linen Issue",
			"kind": kind,
			"department": department,
			"issued_by": employee,
			"station": station,
			"recipient": recipient,
			"sign_method": sign_method,
			"signature": signature,
			"signed_at": now_datetime(),
			"note": note,
			"lines": rows,
		}
	)
	doc.insert()
	doc.submit()
	return doc


def view(doc):
	"""Phiếu cấp phát đã ghi sổ cho màn trạm, kèm cảnh báo định mức và đối chiếu mới."""
	return {
		"issue": doc.name,
		"kind": doc.kind,
		"department": doc.department,
		"issued_at": str(doc.issued_at),
		"recipient": doc.recipient,
		"recipient_name": doc.recipient_name,
		"total_qty": doc.total_qty,
		"total_weight_kg": doc.total_weight_kg,
		"quota_warning": doc.quota_warning,
		"lines": [
			{
				"linen_type": row.linen_type,
				"qty": row.qty,
				"weight_kg": row.weight_kg,
				"weight_source": row.weight_source,
				"variance_note": row.variance_note,
			}
			for row in doc.lines
		],
		"balance": reconcile.balance(doc.department),
	}
