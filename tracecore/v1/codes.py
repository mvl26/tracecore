"""RPC tracecore.v1.codes.*: mã đối tượng QR nội bộ (FEAT-005, FR-M9-07, A-05 R3/R4).

- `issue_rolls`: R10/System Manager cấp hàng loạt mã cuộn nhãn ``CN-#####`` cho một Item nhóm Nhãn (1-200 mã), cả loạt
  trong một transaction qua `core.code_registry.next_code`: lỗi giữa chừng hoàn tác hết, kể cả bộ đếm (không thủng số).
- `list_rolls`: R10/System Manager liệt kê mã cuộn ``CN-`` còn ``Active`` của một Item nhãn (chỉ đọc) để in lại nhãn
  cuộn đã cấp (lần in trước lỗi, nhãn mất/hỏng) bằng nút "In nhãn cuộn" trên form Item.
- `resolve_object`: tra đối tượng của một mã để in nhãn QR (`v1.print.object_label`, `object_preview`): mã phải đúng
  định dạng của loại đối tượng, có trong Code Registry và còn ``Active``; thiết bị ``Retired`` bị chặn (R4).

Quyền kiểm TRƯỚC mọi thao tác ghi; từ chối nghiệp vụ: body chuẩn ``{"ok": false, "error"}`` + mã HTTP + Audit Log
`Reject` (`reject_block`).
"""

import frappe
from frappe import _

from tracecore.core import code_registry, gs1
from tracecore.core import print as core_print
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import reject_block, require_any_role

ROLL_ROLES = ("TC R10", "System Manager")
MAX_ROLLS = 200
MAX_LIST_ROLLS = 500  # danh sách in lại: cỡ hộp thoại chọn mã; quá thì báo `truncated`
SAVEPOINT = "tc_issue_rolls"
# Đối tượng có DocType riêng: mã trong sổ phải trỏ tới đúng DocType này
OBJECT_DOCTYPES = {"Equipment": "Equipment", "Station": "Zone Station", "Roll": "Item"}


def _block(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _is_label_item(item):
	"""Item thuộc nhóm Nhãn và có phương pháp tương thích (máy in chọn theo phương pháp, BRU-REP-011)."""
	if not isinstance(item, str) or not item:
		return False
	row = frappe.db.get_value("Item", item, ["tc_item_group_cssd", "tc_compatible_method"], as_dict=True)
	return bool(row and row.tc_item_group_cssd == "Label" and row.tc_compatible_method)


def _roll_count(value):
	"""Số mã cần cấp: số nguyên (hoặc chuỗi chữ số từ hộp thoại Desk) trong 1..MAX_ROLLS, ngược lại None."""
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		number = value
	elif isinstance(value, str) and value.strip().isdigit():
		number = int(value.strip())
	else:
		return None
	return number if 1 <= number <= MAX_ROLLS else None


@frappe.whitelist(methods=["POST"])
@idempotent
def issue_rolls(item, count, client_ts=None):
	"""Cấp `count` mã cuộn nhãn ``CN-#####`` liên tiếp cho Item nhãn `item`; trả ``{"ok": true, "codes", "item"}``.

	Mỗi mã ghi Code Registry (prefix ``CN``, ref Item). Từ chối: ``ROLL_NOT_LABEL`` (422: Item không có hoặc không
	phải nhãn có phương pháp), ``COUNT_OUT_OF_RANGE`` (422: số lượng ngoài 1-200).
	"""
	require_any_role(*ROLL_ROLES)
	timestamp = parse_client_ts(client_ts)
	ref_name = item if isinstance(item, str) else None
	if not _is_label_item(item):
		return reject_block(
			Block(
				"ROLL_NOT_LABEL",
				_("Not a label item"),
				_("Item {0} is not a label item with a compatible method.").format(ref_name or "-"),
				_(
					"Open a label item (group Label, with a compatible method) and issue the roll codes there."
				),
			),
			"Item",
			ref_name,
			client_ts=timestamp,
		)
	number = _roll_count(count)
	if number is None:
		return reject_block(
			Block(
				"COUNT_OUT_OF_RANGE",
				_("Quantity out of range"),
				_("The number of roll codes must be a whole number from 1 to {0}.").format(MAX_ROLLS),
				_("Enter a quantity from 1 to {0}.").format(MAX_ROLLS),
			),
			"Item",
			item,
			client_ts=timestamp,
		)
	frappe.db.savepoint(SAVEPOINT)
	try:
		codes = [code_registry.next_code(code_registry.ROLL_PREFIX, "Item", item) for _index in range(number)]
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)  # cả loạt hoặc không mã nào (Review Focus 1)
		raise
	return {"ok": True, "codes": codes, "item": item}


@frappe.whitelist()
def list_rolls(item):
	"""Mã cuộn ``CN-`` còn ``Active`` của Item nhãn `item`, tăng dần: ``{"ok": true, "item", "codes", "truncated"}``.

	Chỉ đọc; quyền kiểm trước. Item không có hoặc không phải nhãn có phương pháp → ``ROLL_NOT_LABEL`` (422). Tối đa
	`MAX_LIST_ROLLS` mã (``truncated`` = còn nữa); in vẫn theo lô tối đa 50 mã mỗi lần ở Desk.
	"""
	require_any_role(*ROLL_ROLES)
	if not _is_label_item(item):
		return reject_block(
			Block(
				"ROLL_NOT_LABEL",
				_("Not a label item"),
				_("Item {0} is not a label item with a compatible method.").format(
					item if isinstance(item, str) and item else "-"
				),
				_(
					"Open a label item (group Label, with a compatible method) and print its roll labels there."
				),
			),
			"Item",
			item if isinstance(item, str) else None,
		)
	codes = frappe.get_all(
		"Code Registry",
		filters={
			"prefix": code_registry.ROLL_PREFIX,
			"ref_doctype": "Item",
			"ref_name": item,
			"status": "Active",
		},
		pluck="name",
		order_by="name asc",
		limit_page_length=MAX_LIST_ROLLS + 1,
	)
	return {
		"ok": True,
		"item": item,
		"codes": codes[:MAX_LIST_ROLLS],
		"truncated": len(codes) > MAX_LIST_ROLLS,
	}


def _not_found(label_object, code):
	if label_object == "Equipment":
		return _block(
			"EQUIPMENT_NOT_FOUND",
			_("Equipment not found"),
			_("Equipment {0} does not exist in TraceCore.").format(code),
			_("Check the QR code on the equipment or call R10."),
		)
	if label_object == "Roll":
		return _block(
			"ROLL_NOT_FOUND",
			_("Label roll not found"),
			_("Roll code {0} has not been issued or has been disabled.").format(code),
			_("Issue roll codes from the label item, or call R10."),
		)
	return _block(
		"CODE_NOT_FOUND",
		_("Code not found"),
		_("Code {0} has not been issued in TraceCore.").format(code),
		_("Print the label from the record of this object, or call R10."),
	)


def _ref_title(doctype, name):
	"""Tên hiển thị của bản ghi (trường tiêu đề của DocType, không có thì tên bản ghi); không có bản ghi → None."""
	if not doctype or not name or not frappe.db.exists(doctype, name):
		return None
	title_field = frappe.get_meta(doctype).get_title_field()
	return frappe.db.get_value(doctype, name, title_field) or name


def _object_details(label_object, code, ref_doctype, ref_name):
	"""``(ref_doctype, ref_name, title, subtitle)`` của đối tượng đã qua kiểm sổ; đối tượng không có → BlockedError."""
	if label_object == "Equipment":
		row = frappe.db.get_value("Equipment", code, ["equipment_name", "equipment_type"], as_dict=True)
		if not row:
			raise _not_found(label_object, code)
		return "Equipment", code, row.equipment_name, _(row.equipment_type, context="Equipment")
	if label_object == "Station":
		row = frappe.db.get_value(
			"Zone Station",
			{"name": code, "is_zone": 0},
			["zone_station_name", "parent_zone", "station_step"],
			as_dict=True,
		)
		if not row:
			raise _not_found(label_object, code)
		zone = _ref_title("Zone Station", row.parent_zone)
		return "Zone Station", code, row.zone_station_name, " - ".join(filter(None, (zone, row.station_step)))
	if label_object == "Roll":
		if not _is_label_item(ref_name):
			raise _block(
				"ROLL_NOT_LABEL",
				_("Not a label roll"),
				_("Roll code {0} does not belong to a label item with a compatible method.").format(code),
				_("Check the label item of this roll, or call R10."),
			)
		row = frappe.db.get_value("Item", ref_name, ["item_name", "tc_compatible_method"], as_dict=True)
		return "Item", ref_name, row.item_name, _(row.tc_compatible_method)
	# thẻ nhân viên, kệ: chưa có DocType riêng (A-05 R6), đối tượng là bản ghi mà sổ trỏ tới
	title = _ref_title(ref_doctype, ref_name)
	if title is None:
		return None, None, "", ""
	return ref_doctype, ref_name, title, _(ref_doctype)


def resolve_object(label_object, code):
	"""Đối tượng in nhãn QR của mã `code`: ``{"code", "ref_doctype", "ref_name", "title", "subtitle"}``.

	Từ chối bằng `BlockedError`: mã sai định dạng hoặc sai loại → ``SCAN_INVALID`` (422); chưa cấp →
	``EQUIPMENT_NOT_FOUND`` / ``ROLL_NOT_FOUND`` / ``CODE_NOT_FOUND`` (404); thiết bị ``Retired`` →
	``EQUIPMENT_RETIRED`` (409, kể cả dữ liệu cũ còn mã Active); mã ``Disabled`` → ``CODE_DISABLED`` (409); cuộn của
	Item không còn là nhãn → ``ROLL_NOT_LABEL`` (422).
	"""
	code = gs1.clean_scan(code) if isinstance(code, str) else code
	problem = core_print.object_code_problem(label_object, code)
	if problem:
		raise _block(
			"SCAN_INVALID", _("Invalid code"), problem, _("Print the label from the record of this object.")
		)
	row = frappe.db.get_value("Code Registry", code, ["status", "ref_doctype", "ref_name"], as_dict=True)
	expected = OBJECT_DOCTYPES.get(label_object)
	if not row or (expected and row.ref_doctype != expected):
		raise _not_found(label_object, code)
	if label_object == "Equipment" and frappe.db.get_value("Equipment", code, "status") == "Retired":
		raise _block(
			"EQUIPMENT_RETIRED",
			_("Equipment retired"),
			_("Equipment {0} is retired; its QR label can no longer be printed.").format(code),
			_("Look up the equipment history instead, or call R10."),
		)
	if row.status != "Active":
		raise _block(
			"CODE_DISABLED",
			_("Code disabled"),
			_("Code {0} has been disabled, so its label cannot be printed.").format(code),
			_("Look up the history of this code instead, or call R10."),
		)
	ref_doctype, ref_name, title, subtitle = _object_details(
		label_object, code, row.ref_doctype, row.ref_name
	)
	return {
		"code": code,
		"ref_doctype": ref_doctype,
		"ref_name": ref_name,
		"title": title,
		"subtitle": subtitle,
	}
