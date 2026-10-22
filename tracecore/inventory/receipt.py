"""Nhập kho vật tư tiêu hao CSSD theo lô/hạn bằng ``Stock Entry`` Material Receipt (FEAT-041, FR-M6-01).

Luật nằm ở một hàm kiểm dòng thuần ``check_lines`` mà mọi đường nhập dùng chung (form Desk qua hook
``Stock Entry.before_validate``, RPC kiểm/ghi Excel của Task 4), nên không có đường nào lách luật:

* thiếu hạn của nhóm bắt buộc hạn (V3) hoặc Item bật cờ có hạn dùng -> ``EXPIRY_REQUIRED``;
* hạn < hôm nay -> ``EXPIRY_PAST`` (hạn đúng hôm nay vẫn nhận, V8);
* lô trùng mã: cùng Item và cùng hạn -> dùng lại Batch; khác hạn / thuộc Item khác -> chặn (V10).

Thứ tự trong ERPNext 15.123 (đã kiểm ở mã nguồn): ``Stock Entry.on_submit`` -> ``make_bundle_using_old_serial_batch_fields``
dựng Serial and Batch Bundle từ ``batch_no`` của dòng, nên Batch phải tồn tại trước ``on_submit``; Link ``batch_no``
còn được kiểm sau ``before_validate``. Vì vậy ``prepare_receipt`` (``before_validate``) tạo Batch đúng lúc
``doc._action == "submit"`` và chỉ khi đó mới gán ``batch_no``; lưu nháp không tạo Batch nào.
"""

from dataclasses import dataclass
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, getdate, nowdate

from tracecore.inventory.items import CSSD_GROUPS, requires_expiry

MATERIAL_RECEIPT = "Material Receipt"
MAX_BATCH_ID = 140  # độ dài tên Batch của ERPNext


class ReceiptInvalid(frappe.ValidationError):
	"""Phiếu nhập có dòng/đầu phiếu sai luật; ``issues`` là danh sách ``LineIssue`` đầy đủ."""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.issues: list[LineIssue] = []


@dataclass(frozen=True)
class ReceiptLine:
	row: int
	item_code: str
	batch_id: str | None
	expiry: date | None
	qty: float
	rate: float


@dataclass(frozen=True)
class LineIssue:
	row: int  # số dòng (trong phiếu hoặc trong Excel); 0 = lỗi đầu phiếu
	code: str
	field: str
	reason: str  # đã qua _()


def today_vn() -> date:
	"""Hôm nay theo múi giờ của System Settings (Asia/Ho_Chi_Minh)."""
	return getdate(nowdate())


def _fmt(value: date | None) -> str:
	return formatdate(value) if value else "-"


def check_header(supplier: str | None, document_no: str | None, warehouse: str | None) -> list[LineIssue]:
	"""Đầu phiếu: nhà cung cấp, số chứng từ, kho nhận bắt buộc (UC-24 bước 3)."""
	issues: list[LineIssue] = []
	if not (supplier or "").strip():
		issues.append(
			LineIssue(0, "SUPPLIER_REQUIRED", "supplier", _("Supplier is required. Choose the supplier."))
		)
	if not (document_no or "").strip():
		issues.append(
			LineIssue(
				0,
				"DOCUMENT_REQUIRED",
				"document_no",
				_("Supplier document number is required. Enter the delivery note or invoice number."),
			)
		)
	if not (warehouse or "").strip():
		issues.append(
			LineIssue(
				0,
				"WAREHOUSE_REQUIRED",
				"warehouse",
				_("Receiving warehouse is required. Choose the warehouse."),
			)
		)
	return issues


def zero_rate_rows(lines: list[ReceiptLine]) -> list[int]:
	"""Dòng đơn giá 0 (UC-24 E2: cảnh báo cam, không chặn)."""
	return [line.row for line in lines if line.qty and flt(line.qty) > 0 and flt(line.rate) == 0]


def check_lines(lines: list[ReceiptLine], today: date) -> list[LineIssue]:
	"""Kiểm mọi dòng nhập kho; trả TẤT CẢ lỗi (không dừng ở lỗi đầu), không ghi DB.

	Mỗi dòng theo thứ tự: Item -> số lượng/đơn giá -> lô -> hạn dùng -> lô đã có / lô trong cùng phiếu.
	"""
	issues: list[LineIssue] = []
	in_document: dict[str, tuple[str, date | None, int]] = {}  # batch (chữ thường) -> (item, hạn, dòng đầu)
	for line in lines:
		item_ok = _check_item(line, issues)
		_check_numbers(line, issues)
		batch_id = (line.batch_id or "").strip()
		if not batch_id:
			issues.append(
				LineIssue(
					line.row,
					"BATCH_REQUIRED",
					"batch_id",
					_(
						"Item {0}: lot (batch) number is required. Enter the lot number printed on the package."
					).format(line.item_code),
				)
			)
		elif len(batch_id) > MAX_BATCH_ID:
			issues.append(
				LineIssue(
					line.row,
					"BATCH_ID_INVALID",
					"batch_id",
					_("Item {0}: lot number is longer than {1} characters. Shorten the lot number.").format(
						line.item_code, MAX_BATCH_ID
					),
				)
			)
		if item_ok:
			_check_expiry(line, today, issues)
		if batch_id and len(batch_id) <= MAX_BATCH_ID:
			_check_lot(line, batch_id, in_document, issues)
	return issues


def _check_item(line: ReceiptLine, issues: list[LineIssue]) -> bool:
	"""Item tồn tại, đang dùng, thuộc nhóm CSSD, theo dõi lô. Trả True nếu kiểm hạn dùng tiếp được."""
	values = (
		frappe.db.get_value(
			"Item",
			line.item_code,
			["disabled", "tc_item_group_cssd", "has_batch_no"],
			as_dict=True,
		)
		if line.item_code
		else None
	)
	if not values:
		issues.append(
			LineIssue(
				line.row,
				"ITEM_NOT_FOUND",
				"item_code",
				_("Item {0} does not exist. Check the item code or create the item first.").format(
					line.item_code or "-"
				),
			)
		)
		return False
	if cint(values.disabled):
		issues.append(
			LineIssue(
				line.row,
				"ITEM_DISABLED",
				"item_code",
				_("Item {0} is disabled. Enable the item or choose another one.").format(line.item_code),
			)
		)
		return False
	if values.tc_item_group_cssd not in CSSD_GROUPS:
		issues.append(
			LineIssue(
				line.row,
				"ITEM_NOT_CSSD",
				"item_code",
				_("Item {0} is not a CSSD consumable. Set its CSSD item group first.").format(line.item_code),
			)
		)
		return False
	if not cint(values.has_batch_no):
		issues.append(
			LineIssue(
				line.row,
				"ITEM_NOT_BATCHED",
				"item_code",
				_("Item {0} does not track lots. Enable Has Batch No on the item.").format(line.item_code),
			)
		)
		return False
	return True


def _check_numbers(line: ReceiptLine, issues: list[LineIssue]) -> None:
	if not flt(line.qty) > 0:
		issues.append(
			LineIssue(
				line.row,
				"QTY_INVALID",
				"qty",
				_("Item {0}: quantity must be greater than 0. Enter the received quantity.").format(
					line.item_code
				),
			)
		)
	if flt(line.rate) < 0:
		issues.append(
			LineIssue(
				line.row,
				"RATE_NEGATIVE",
				"rate",
				_("Item {0}: unit price cannot be negative. Enter 0 or a positive price.").format(
					line.item_code
				),
			)
		)


def _check_expiry(line: ReceiptLine, today: date, issues: list[LineIssue]) -> None:
	needs = requires_expiry(line.item_code)
	if needs and not line.expiry:
		issues.append(
			LineIssue(
				line.row,
				"EXPIRY_REQUIRED",
				"expiry_date",
				_("Item {0} must have an expiry date. Enter the expiry date printed on the package.").format(
					line.item_code
				),
			)
		)
	elif line.expiry and not needs:
		issues.append(
			LineIssue(
				line.row,
				"EXPIRY_NOT_TRACKED",
				"expiry_date",
				_(
					"Item {0} does not track expiry dates. Turn on Has Expiry Date on the item, or leave the expiry date empty."
				).format(line.item_code),
			)
		)
	if line.expiry and line.expiry < today:
		issues.append(
			LineIssue(
				line.row,
				"EXPIRY_PAST",
				"expiry_date",
				_(
					"Item {0}: the lot expired on {1}. Expired lots are not accepted; return it to the supplier."
				).format(line.item_code, _fmt(line.expiry)),
			)
		)


def _check_lot(
	line: ReceiptLine,
	batch_id: str,
	in_document: dict[str, tuple[str, date | None, int]],
	issues: list[LineIssue],
) -> None:
	key = batch_id.lower()
	seen = in_document.get(key)
	if seen is None:
		in_document[key] = (line.item_code, line.expiry, line.row)
	else:
		first_item, first_expiry, first_row = seen
		if first_item != line.item_code:
			issues.append(
				LineIssue(
					line.row,
					"BATCH_ITEM_MISMATCH",
					"batch_id",
					_("Lot {0} is already used for item {1} on row {2}. Use a different lot number.").format(
						batch_id, first_item, first_row
					),
				)
			)
			return
		if line.expiry and first_expiry and line.expiry != first_expiry:
			issues.append(
				LineIssue(
					line.row,
					"LOT_CONFLICT_IN_DOCUMENT",
					"expiry_date",
					_(
						"Lot {0} has expiry {1} here but {2} on row {3}. One lot has one expiry date; correct one of the rows."
					).format(batch_id, _fmt(line.expiry), _fmt(first_expiry), first_row),
				)
			)
			return
	existing = frappe.db.get_value("Batch", batch_id, ["item", "expiry_date"], as_dict=True)
	if not existing:
		return
	if existing.item != line.item_code:
		issues.append(
			LineIssue(
				line.row,
				"BATCH_ITEM_MISMATCH",
				"batch_id",
				_("Lot {0} already belongs to item {1}. Use a different lot number.").format(
					batch_id, existing.item
				),
			)
		)
	elif line.expiry and existing.expiry_date and getdate(existing.expiry_date) != line.expiry:
		issues.append(
			LineIssue(
				line.row,
				"BATCH_EXPIRY_MISMATCH",
				"expiry_date",
				_(
					"Lot {0} already exists with expiry {1}, not {2}. Correct the expiry date or the lot number."
				).format(batch_id, _fmt(getdate(existing.expiry_date)), _fmt(line.expiry)),
			)
		)


def ensure_batch(item_code: str, batch_id: str, expiry: date | None, supplier: str | None) -> str:
	"""Batch của lô nhập: dùng lại nếu đã có (cùng Item, đã qua ``check_lines``), ngược lại tạo mới.

	Batch mới đặt ``use_batchwise_valuation = 0`` để giá bình quân tính theo Item (V5).
	"""
	batch_id = batch_id.strip()
	existing = frappe.db.get_value("Batch", batch_id, "name")
	if existing:
		return existing
	batch = frappe.get_doc(
		{
			"doctype": "Batch",
			"batch_id": batch_id,
			"item": item_code,
			"expiry_date": expiry,
			"supplier": supplier or None,
		}
	)
	batch.insert(ignore_permissions=True)  # lập phiếu nhập đã đủ quyền tạo lô; Audit Log ghi người dùng thật
	if cint(batch.use_batchwise_valuation):
		# ERPNext đặt =1 cho lô mới và khóa trường (set_only_once): db_set là cách duy nhất qua API tài liệu
		batch.db_set("use_batchwise_valuation", 0, update_modified=False)
	return batch.name


def is_receipt(doc) -> bool:
	purpose = doc.get("purpose")
	if not purpose and doc.get("stock_entry_type"):
		purpose = frappe.db.get_value("Stock Entry Type", doc.stock_entry_type, "purpose")
	return purpose == MATERIAL_RECEIPT


def _cssd_rows(doc) -> list:
	return [
		row
		for row in doc.get("items") or []
		if row.get("item_code")
		and frappe.db.get_value("Item", row.item_code, "tc_item_group_cssd") in CSSD_GROUPS
	]


def _to_date(value) -> date | None:
	return getdate(value) if value else None


def _build_lines(doc, rows: list) -> list[ReceiptLine]:
	lines = []
	for row in rows:
		batch_id = (row.get("tc_batch_id") or row.get("batch_no") or "").strip() or None
		lines.append(
			ReceiptLine(
				row=cint(row.idx),
				item_code=row.item_code,
				batch_id=batch_id,
				expiry=_to_date(row.get("tc_expiry_date")),
				qty=flt(row.get("qty")),
				rate=flt(row.get("basic_rate")),
			)
		)
	return lines


def _format_issues(issues: list[LineIssue]) -> str:
	items = []
	for issue in issues:
		prefix = _("Line {0}").format(issue.row) + ": " if issue.row else ""
		items.append(f"<li>{prefix}{frappe.utils.escape_html(issue.reason)}</li>")
	return (
		_("{0} problem(s) stop this receipt from being saved:").format(len(issues))
		+ f"<ul>{''.join(items)}</ul>"
		+ _("Fix the lines above, then save the receipt again.")
	)


def throw_issues(issues: list[LineIssue], title: str | None = None) -> None:
	"""``frappe.throw`` một lần liệt kê mọi lỗi (tiêu đề -> lý do từng dòng -> hành động)."""
	try:
		frappe.throw(_format_issues(issues), ReceiptInvalid, title=title or _("Cannot receive these items"))
	except ReceiptInvalid as exc:
		exc.issues = list(issues)
		raise


def prepare_receipt(doc, method=None) -> None:
	"""``Stock Entry.before_validate``: luật nhập kho vật tư CSSD cho Material Receipt.

	Chỉ chạy khi phiếu là Material Receipt và có ít nhất một dòng Item CSSD (dòng Item khác không bị đụng tới).
	Lưu nháp cũng kiểm đủ luật (chặn sớm); Batch chỉ được tạo khi ghi sổ.
	"""
	if not is_receipt(doc):
		return
	rows = _cssd_rows(doc)
	if not rows:
		return
	if not (doc.get("company") or _default_company()):
		frappe.throw(
			_("No company is configured for this site. Ask the administrator to finish the ERPNext setup."),
			title=_("Cannot receive these items"),
		)
	lines = _build_lines(doc, rows)
	warehouse = doc.get("to_warehouse") or next(
		(r.get("t_warehouse") for r in rows if r.get("t_warehouse")), None
	)
	issues = check_header(doc.get("tc_supplier"), doc.get("tc_document_no"), warehouse)
	issues += check_lines(lines, today_vn())
	if issues:
		throw_issues(issues)
	zero_rows = set(zero_rate_rows(lines))
	if zero_rows:
		for row in rows:
			if cint(row.idx) in zero_rows:
				row.allow_zero_valuation_rate = 1
		frappe.msgprint(
			_("Row(s) {0} have a unit price of 0; the stock is received with a zero valuation rate.").format(
				", ".join(str(n) for n in sorted(zero_rows))
			),
			title=_("Unit price is 0"),
			indicator="orange",
		)
	if doc.get("_action") == "submit":
		for row, line in zip(rows, lines, strict=True):
			name = ensure_batch(row.item_code, line.batch_id, line.expiry, doc.get("tc_supplier"))
			row.use_serial_batch_fields = 1
			row.batch_no = name


def _default_company() -> str | None:
	import erpnext

	return erpnext.get_default_company()
