"""Phiếu kiểm kê kho (ERPNext Stock Reconciliation): lý do khi lệch lớn, một kho một phiếu mở, khóa xuất nhập thủ công
(FEAT-043; FR-M6-05, .1, .2; UC-26 E1, E2; architecture A-52 C2-C6).

Stock Count của tài liệu thay bằng `Stock Reconciliation` (architecture §5.3). Ghi sổ phiếu chính là phê duyệt: chỉ R02/R09
có quyền `submit` (xem `inventory.permissions`). Phiếu Nháp của một kho là phiếu "đang mở" của kho đó.
"""

import frappe
from frappe import _
from frappe.utils import flt

DOCTYPE = "Stock Reconciliation"
VARIANCE_LIMIT = 0.10  # UC-26 E1: lệch quá 10 % tồn hệ thống thì phải có lý do
MANUAL_SOURCES = (
	None,
	"",
	"Manual Issue",
)  # phiếu thủ công; tiêu hao tự động (FEAT-042) mang tc_source_doctype khác


def _warehouses(doc):
	names = {row.warehouse for row in doc.get("items") or [] if row.get("warehouse")}
	if doc.get("set_warehouse"):
		names.add(doc.set_warehouse)
	return names


def open_counts(warehouses, exclude=None):
	"""Tên các phiếu kiểm kê Nháp có dòng thuộc một trong `warehouses` (trừ phiếu `exclude`)."""
	if not warehouses:
		return []
	filters = {"docstatus": 0, "warehouse": ["in", list(warehouses)], "parenttype": DOCTYPE}
	rows = frappe.get_all("Stock Reconciliation Item", filters=filters, fields=["parent"], distinct=True)
	parents = {row.parent for row in rows if row.parent != exclude}
	# phiếu Nháp đã đánh dấu "bỏ dở" không còn khóa kho (Frappe không cho hủy bản Nháp và phiếu không bị xóa)
	return sorted(name for name in parents if not frappe.db.get_value(DOCTYPE, name, "tc_abandoned"))


def validate(doc, method=None):
	"""Một kho một phiếu mở; dòng lệch > 10 % phải có lý do (hook `validate` của Stock Reconciliation)."""
	others = [] if doc.get("tc_abandoned") else open_counts(_warehouses(doc), exclude=doc.name)
	if others:
		frappe.throw(
			_(
				"A stock count of this warehouse is already open ({0}). Post it, or tick Abandoned on it first."
			).format(", ".join(others))
		)
	for row in doc.items:
		_check_batch_of_item(row)
		if _needs_reason(row) and not (row.get("tc_variance_reason") or "").strip():
			frappe.throw(
				_(
					"Row {0}: the counted quantity differs from the system quantity by more than 10 %. Enter a reason."
				).format(row.idx)
			)


def before_submit(doc, method=None):
	"""Phiếu đã đánh dấu bỏ dở không được ghi sổ (hook `before_submit` của Stock Reconciliation)."""
	if doc.get("tc_abandoned"):
		frappe.throw(_("This count was abandoned and cannot be posted. Untick Abandoned first."))


def only_draft_deletable(doc, method=None):
	"""Chỉ bản Nháp của đề nghị mua mới xóa được; chứng từ đã ghi sổ/hủy giữ lại (hook `on_trash` của Material Request)."""
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft purchase request can be deleted."))


def _check_batch_of_item(row):
	if not row.get("batch_no"):
		return
	owner = frappe.db.get_value("Batch", row.batch_no, "item")
	if owner and owner != row.item_code:
		frappe.throw(
			_("Row {0}: batch {1} does not belong to item {2}.").format(row.idx, row.batch_no, row.item_code)
		)


def _needs_reason(row):
	system = flt(row.get("current_qty"))
	if system <= 0 or row.get("qty") in (None, ""):
		return False
	return abs(flt(row.qty) - system) / system > VARIANCE_LIMIT + 1e-9


def check_warehouse_lock(doc, method=None):
	"""Chặn Stock Entry thủ công của kho đang có phiếu kiểm kê mở (FR-M6-05.2). Tiêu hao tự động không bị chặn: nó chạy
	một lần khi lô/mẻ hoàn tất, chặn sẽ làm mất khoản trừ (A-52 C4)."""
	if doc.get("tc_source_doctype") not in MANUAL_SOURCES:
		return
	warehouses = {row.s_warehouse for row in doc.get("items") or [] if row.get("s_warehouse")}
	warehouses |= {row.t_warehouse for row in doc.get("items") or [] if row.get("t_warehouse")}
	locked = open_counts(warehouses)
	if locked:
		frappe.throw(
			_(
				"The stock of this warehouse is being counted ({0}). Stock entries are locked until the count is posted or abandoned."
			).format(", ".join(locked))
		)
