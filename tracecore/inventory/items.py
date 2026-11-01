"""Luật Item vật tư tiêu hao CSSD (FEAT-041, FR-M6-02; Amendment A-07 V1-V5).

Item là ERPNext ``Item`` + Custom Field ``tc_*``; không có DocType riêng (ADR-009). Hai hook ``doc_events["Item"]``:

* ``check_duplicate_code`` (``before_insert``): chặn trùng mã không phân biệt hoa/thường và khoảng trắng đầu/cuối;
* ``validate_item`` (``validate``): chỉ chạy khi Item có ``tc_item_group_cssd``. Luật **tự bổ sung cờ** (lô, hạn dùng,
  bình quân gia quyền) thay vì chặn, để Item cũ của FEAT-005/014/018 vẫn lưu và sửa được.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

# FR-M6-02.1: 9 nhóm cố định + Lubricant (V1: instrument/maintenance.py lọc lô dầu theo giá trị này).
# Bốn chuỗi cũ (A-02) giữ nguyên, đứng trước, để không vỡ dữ liệu và code M1/M2.
CSSD_GROUPS: tuple[str, ...] = (
	"Packaging",
	"Chemical Indicator",
	"Label",
	"Lubricant",
	"Biological Indicator",
	"Test",
	"Pouch",
	"Filter Box",
	"Chemical",
	"Other",
	"Packaging Accessory",  # A-97
)
# V3: nhóm bắt buộc có hạn dùng (FR-M6-01.1: chỉ thị hóa học, chỉ thị sinh học, hóa chất; dầu là hóa chất)
EXPIRY_REQUIRED_GROUPS: tuple[str, ...] = (
	"Chemical Indicator",
	"Biological Indicator",
	"Chemical",
	"Lubricant",
)
# BRU-REP-011: hai loại nhãn và phương pháp của từng loại
LABEL_METHOD_BY_CODE = {"VT-NHAN-HAP": "Steam", "VT-NHAN-PLASMA": "Plasma"}
LABEL_GROUP = "Label"
CI_GROUP = "Chemical Indicator"
METHODS = ("Steam", "Plasma")
VALUATION_METHOD = "Moving Average"  # V5


def is_cssd_item(item_code: str) -> bool:
	"""Item có nhóm vật tư CSSD (``tc_item_group_cssd``)."""
	return bool(item_code and frappe.db.get_value("Item", item_code, "tc_item_group_cssd"))


def requires_expiry(item_code: str) -> bool:
	"""Nhập kho Item này phải có hạn dùng: nhóm bắt buộc hạn (V3) hoặc Item bật cờ có hạn dùng."""
	if not item_code:
		return False
	values = frappe.db.get_value("Item", item_code, ["tc_item_group_cssd", "has_expiry_date"], as_dict=True)
	if not values:
		return False
	return values.tc_item_group_cssd in EXPIRY_REQUIRED_GROUPS or bool(cint(values.has_expiry_date))


def has_stock_ledger(item_code: str) -> bool:
	"""Item đã có Stock Ledger Entry (ERPNext không cho đổi cờ lô/định giá nữa)."""
	return bool(item_code) and bool(
		frappe.db.exists("Stock Ledger Entry", {"item_code": item_code, "is_cancelled": 0})
	)


def check_duplicate_code(doc, method=None) -> None:
	"""``Item.before_insert``: cắt khoảng trắng mã và chặn trùng không phân biệt hoa/thường (FR-M6-02.3)."""
	code = (doc.get("item_code") or "").strip()
	if not code:
		return
	doc.item_code = code
	rows = frappe.db.sql("select name from `tabItem` where lower(item_code) = %s limit 1", code.lower())
	if rows:
		frappe.throw(
			_("Item code {0} already exists (item {1}).").format(code, rows[0][0])
			+ " "
			+ _("Use a different code or open the existing item."),
			frappe.DuplicateEntryError,
			title=_("Duplicate Item Code"),
		)


def validate_item(doc, method=None) -> None:
	"""``Item.validate``: luật nhóm vật tư CSSD (V1-V5)."""
	group = doc.get("tc_item_group_cssd")
	if not group:
		return
	# doc.flags.tc_legacy_data: chỉ factories.make_item đặt, để dựng Item "cũ" (trước FEAT-041) cho test của
	# FEAT-005/014/018; không có đường nào trong sản phẩm đặt cờ này.
	if group not in CSSD_GROUPS:
		_throw(
			_("CSSD item group {0} is not in the fixed list.").format(group),
			_("Choose a group from the list."),
		)
	_validate_method(doc, group)
	_validate_ci_class(doc, group)
	_apply_stock_rules(doc, group)
	_validate_reorder_levels(doc)


def _throw(reason: str, action: str) -> None:
	frappe.throw(f"{reason} {action}", title=_("Invalid Consumable Item"))


def _validate_method(doc, group: str) -> None:
	method = doc.get("tc_compatible_method")
	if group == LABEL_GROUP and not method and not doc.flags.tc_legacy_data:
		_throw(
			_("Label items need a Compatible Method."),
			_("Set Compatible Method to Steam or Plasma."),
		)
	if method and method not in METHODS:
		_throw(_("Compatible Method {0} is not valid.").format(method), _("Choose Steam or Plasma."))
	code = (doc.get("item_code") or "").strip().upper()
	expected = LABEL_METHOD_BY_CODE.get(code)
	if expected and (group != LABEL_GROUP or method != expected):
		_throw(
			_("Item {0} must be a Label item with Compatible Method {1}.").format(code, expected),
			_("Set the group to Label and the Compatible Method to {0}.").format(expected),
		)


def _validate_ci_class(doc, group: str) -> None:
	if doc.get("tc_ci_class") and group != CI_GROUP:
		_throw(
			_("Chemical Indicator Class applies only to the Chemical Indicator group."),
			_("Clear Chemical Indicator Class or change the group."),
		)


def _apply_stock_rules(doc, group: str) -> None:
	"""Cờ kho/lô/hạn/định giá. Không throw trừ khi Item đã có tồn mà định giá khác bình quân (V5)."""
	has_stock = has_stock_ledger(doc.name) if not doc.is_new() else False
	if has_stock:
		if (doc.get("valuation_method") or "") != VALUATION_METHOD:
			_throw(
				_("Item {0} already has stock but its valuation method is {1}.").format(
					doc.name, doc.get("valuation_method") or "-"
				),
				_("Consumable items use Moving Average; ask the accountant to correct the valuation method."),
			)
		return
	if doc.flags.tc_legacy_data:
		return
	doc.is_stock_item = 1
	doc.has_batch_no = 1
	doc.valuation_method = VALUATION_METHOD
	if group in EXPIRY_REQUIRED_GROUPS:
		doc.has_expiry_date = 1


def _validate_reorder_levels(doc) -> None:
	seen: set[str] = set()
	for row in doc.get("reorder_levels") or []:
		if not row.get("material_request_type"):
			row.material_request_type = "Purchase"
		warehouse = row.get("warehouse")
		if not warehouse:
			continue
		if warehouse in seen:
			_throw(
				_("Row #{0}: warehouse {1} appears more than once in the minimum stock table.").format(
					row.idx, warehouse
				),
				_("Keep one row per warehouse."),
			)
		seen.add(warehouse)
		if flt(row.get("warehouse_reorder_level")) < 0:
			_throw(
				_("Row #{0}: minimum stock cannot be negative.").format(row.idx),
				_("Enter 0 or a positive quantity."),
			)
		if cint(frappe.db.get_value("Warehouse", warehouse, "is_group")):
			_throw(
				_("Row #{0}: {1} is a group warehouse.").format(row.idx, warehouse),
				_("Choose a leaf warehouse that holds stock."),
			)
