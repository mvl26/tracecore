"""Nhãn QR của lô vật tư/chỉ thị (FEAT-082, A-118, FR-M6-09): QR chứa đúng tên `Batch`.

Không thêm mã mới và không ghi `Code Registry`: ô lô ở trạm vốn nhận chuỗi quét trùng tên Batch (`lots.lot_code`). Chỉ in
lô còn hạn và chưa vô hiệu; mỗi lô in ra ghi một dòng Audit Log. Nhãn là PDF khổ nhãn chung (A-114, A-116), nhiều lô
gộp một PDF nhiều trang để mở một hộp thoại In.
"""

import frappe
from frappe import _
from frappe.utils import formatdate, getdate

from tracecore.core import audit, label_pdf, lots
from tracecore.core.errors import Block, BlockedError

MAX_LABELS = 50  # cùng giới hạn in hàng loạt của Desk (tracecore.codes.MAX_BULK)
CODE_MAX_LENGTH = 40


def _printable_payload(name):
	return (
		isinstance(name, str)
		and 0 < len(name) <= CODE_MAX_LENGTH
		and all("!" <= char <= "}" and char != "^" for char in name)
	)


def problem(batch):
	"""Lý do (đã dịch) `batch` không in được nhãn QR, hoặc None khi in được."""
	row = (
		frappe.db.get_value("Batch", batch, ["item", "expiry_date", "disabled"], as_dict=True)
		if isinstance(batch, str)
		else None
	)
	if not row:
		return _("Lot {0} does not exist.").format(batch)
	if row.disabled:
		return _("Lot {0} is disabled.").format(batch)
	if row.expiry_date and getdate(row.expiry_date) < lots.today_vn():
		return _("Lot {0} expired on {1}.").format(batch, formatdate(row.expiry_date, "dd/mm/yyyy"))
	if not _printable_payload(batch):
		return _(
			"Lot name {0} cannot be printed on a QR label (use 1-{1} characters without spaces)."
		).format(batch, CODE_MAX_LENGTH)
	return None


def _lines(batch):
	row = frappe.db.get_value("Batch", batch, ["item", "expiry_date"], as_dict=True)
	item_name = frappe.db.get_value("Item", row.item, "item_name") or row.item
	expiry = (
		_("Expiry date: {0}").format(formatdate(row.expiry_date, "dd/mm/yyyy")) if row.expiry_date else ""
	)
	return item_name, expiry


def pdf(batches):
	"""``(bytes PDF hoặc None, [lô đã in], [{"batch", "reason"}])``; lô không in được bị bỏ qua kèm lý do."""
	names = list(dict.fromkeys(batch for batch in batches if isinstance(batch, str)))[:MAX_LABELS]
	pages, printed, skipped = [], [], []
	for name in names:
		reason = problem(name)
		if reason:
			skipped.append({"batch": name, "reason": reason})
			continue
		title, subtitle = _lines(name)
		pages.append(label_pdf.object_pdf(name, title, subtitle))
		printed.append(name)
	if not pages:
		return None, printed, skipped
	for name in printed:
		audit.log(
			"Update",
			"Batch",
			name,
			new={"event": "BatchLabelPrinted"},
			reason="BatchLabelPrinted",
		)
	return label_pdf.merge(pages), printed, skipped


def render(batches):
	"""``{"pdf_b64", "filename", "printed", "skipped"}``; không lô nào in được → `BlockedError` có lý do từng lô."""
	document, printed, skipped = pdf(batches)
	if document is None:
		raise BlockedError(
			Block(
				"CONSUMABLE_LOT_INVALID",
				_("No lot label can be printed"),
				"; ".join(row["reason"] for row in skipped) or _("No lot was chosen."),
				_("Choose lots that have not expired and are not disabled."),
				items=[row["batch"] for row in skipped],
			)
		)
	filename = f"{printed[0]}.pdf" if len(printed) == 1 else f"LOT-LABELS-{len(printed)}.pdf"
	return {**label_pdf.encode(document, filename), "printed": printed, "skipped": skipped}
