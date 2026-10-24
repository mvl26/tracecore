"""Tiếp nhận đồ bẩn tại T1 (M2, FEAT-019, UC-05): mở phiếu bằng thẻ người giao, quét nhiều bộ, xác nhận thành phần, ghi sổ.

- Mở/tiếp tục/hủy phiếu: `open_receipt`, `departments`, `discard` (FR-M2-01, FR-M2-01.7).
- Quét bộ: `scan_set` (trạng thái hợp T1, trùng, BOM + ảnh, tiếp nhận cưỡng bức của R02; FR-M2-02, FR-M2-23).
- Xác nhận: `confirm_line` (tick, Xác nhận tất cả, ghi chú bất thường, Xác nhận bộ), `attach_photo` (FR-M2-23.1 đến .6).
- Ghi sổ: `submit` (mở chu trình, ghim BOM, cổng T1 Đạt, hủy Cycle ID chưa dùng; FR-M2-01.3, .4, FR-M2-25).

M2 không import M1/M8 (lint R1): BOM và ảnh lấy qua hook ``tracecore_receipt_context``. Trạng thái Set Unit chỉ đổi qua
`core.step_gate` (`start_cycle`, `record`); phiếu chỉ đổi ở đây bằng cờ ``flags.tc_receiving``. Từ chối nghiệp vụ là
`BlockedError` (mã HTTP ở `core.errors`). Mọi hàm nhận `station` và `receiver` (Employee đăng nhập thẻ) của phiên trạm.
"""

import contextlib
import io

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import client_time, extension, gs1, station_auth, step_gate
from tracecore.core.errors import Block, BlockedError

STEP = "T1"
SAVEPOINT = "tc_receipt_submit"
DRAFT = 0
PHOTO_MAX_BYTES = 5 * 1024 * 1024
PHOTO_MAX_PIXELS = 40_000_000
PHOTO_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
REVIEWER_ROLE = "TC R02"  # tiếp nhận cưỡng bức (FR-M2-02.2, A-33)
FORCE_STATUSES = ("Processing", "Reprocess", "Sterile")  # Disposed, End of Life không cưỡng bức được
UNUSED_PACK_END_STATUSES = ("Used", "Void", "Recalled")
AFTER_FORCE_HOOK = "tracecore_after_force_receive"
RECEIPT_CONTEXT_HOOK = "tracecore_receipt_context"
EMPLOYEE_FIELDS = ("name", "employee_name", "department", "status", "tc_card_enabled")


def _blocked(code, title, reason, action, items=None):
	return BlockedError(Block(code, title, reason, action, items=items))


def _system_time(utc):
	"""Giờ UTC không múi giờ (kết quả `parse_client_ts`) → giờ hệ thống (Asia/Ho_Chi_Minh) không múi giờ."""
	return client_time.to_system_time(utc)


# --- Phiếu nháp: tìm, khóa, kiểm chủ ---------------------------------------------------------------------


def _not_found(receipt):
	return _blocked(
		"RECEIPT_NOT_FOUND",
		_("Receipt not found"),
		_("Receipt {0} does not exist for this receiver at this station.").format(receipt or "-"),
		_("Scan the deliverer's employee card to open a new receipt."),
	)


def _closed(receipt):
	return _blocked(
		"RECEIPT_CLOSED",
		_("Receipt is closed"),
		_("Receipt {0} was already submitted or dropped.").format(receipt),
		_("Scan the deliverer's employee card to open a new receipt."),
	)


def _draft(receipt, station, receiver, lock=True):
	"""Phiếu nháp của (`receiver`, `station`); không phải của họ → RECEIPT_NOT_FOUND, đã đóng → RECEIPT_CLOSED."""
	row = (
		frappe.db.get_value(
			"Dirty Receipt", receipt, ["name", "receiver", "station", "docstatus", "abandoned"], as_dict=True
		)
		if isinstance(receipt, str) and receipt
		else None
	)
	if not row or row.receiver != receiver or row.station != station:
		raise _not_found(receipt)
	if cint(row.docstatus) != DRAFT or cint(row.abandoned):
		raise _closed(receipt)
	doc = frappe.get_doc("Dirty Receipt", row.name, for_update=lock)
	doc.flags.tc_receiving = True
	return doc


def _save(doc):
	doc.flags.tc_receiving = True
	doc.set_count = len(doc.items)
	doc.flagged_count = sum(1 for item in doc.items if cint(item.needs_review))
	doc.save(ignore_permissions=True)


def _current_draft(station, receiver):
	return frappe.db.get_value(
		"Dirty Receipt",
		{"receiver": receiver, "station": station, "docstatus": DRAFT, "abandoned": 0},
		"name",
		order_by="creation desc",
	)


# --- Người giao ---------------------------------------------------------------------------------------


def departments():
	"""Khoa chọn được khi người giao không có thẻ (FR-M2-01.7): khoa lá, chưa tắt, theo tên."""
	return frappe.get_all(
		"Department",
		filters={"is_group": 0, "disabled": 0},
		fields=["name", "department_name"],
		order_by="department_name asc",
	)


def _employee_by_card(card):
	return frappe.db.get_value(
		"Employee", {"tc_card_id": station_auth.normalize_card_id(card)}, list(EMPLOYEE_FIELDS), as_dict=True
	)


def _deliverer_from_card(raw):
	"""Employee người giao từ chuỗi quét `raw` (mã thẻ ``NV-#####`` hoặc thẻ bệnh viện có sẵn); khoa lấy từ thẻ."""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] not in ("employee", "unknown"):
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} is not an employee card.").format(scanned["raw"] or "-"),
			_("Scan the employee card of the person who hands the sets over."),
		)
	employee = _employee_by_card(raw)
	if scanned["type"] == "unknown" and not employee:
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} was not issued by TraceCore.").format(scanned["raw"] or "-"),
			_("Scan the employee card of the person who hands the sets over."),
		)
	if not employee or employee.status != "Active" or not cint(employee.tc_card_enabled):
		raise _blocked(
			"DELIVERER_NOT_FOUND",
			_("Employee card not recognised"),
			_("Card {0} does not belong to an active employee, or it is disabled.").format(scanned["raw"] or "-"),
			_("Check the card, or choose the department and type the name if the person has no card."),
		)
	if not employee.department:
		raise _blocked(
			"DELIVERER_NO_DEPARTMENT",
			_("Card has no department"),
			_("Employee {0} has no department, so the returning department cannot be taken from the card.").format(
				employee.employee_name or employee.name
			),
			_("Choose the department and type the name, then ask R02 to complete the employee record."),
		)
	return employee


def _manual_deliverer(department, name):
	row = frappe.db.get_value("Department", department, ["is_group", "disabled"], as_dict=True) if department else None
	if not row or cint(row.is_group) or cint(row.disabled):
		raise _blocked(
			"DEPARTMENT_INVALID",
			_("Department is not valid"),
			_("Department {0} does not exist, is disabled, or is a group.").format(department or "-"),
			_("Choose the department that returns the sets."),
		)
	name = (name or "").strip()
	if not name:
		raise _blocked(
			"DELIVERER_NAME_REQUIRED",
			_("Deliverer name is required"),
			_("The deliverer has no card, so the name must be typed."),
			_("Type the name of the person who hands the sets over."),
		)
	return name


# --- Mở, tiếp tục, hủy phiếu -----------------------------------------------------------------------------


def open_receipt(station, receiver, client_ts, raw=None, department=None, deliverer_name=None):
	"""Mở phiếu nháp mới từ thẻ người giao `raw` hoặc từ khoa + tên (người giao không có thẻ); không có cả hai thì
	tiếp tục phiếu nháp gần nhất của (`receiver`, `station`), hoặc trả None.

	Mở phiếu mới đóng (``abandoned``) phiếu nháp cũ của cùng người nhận và trạm. `client_ts` là UTC không múi giờ.
	Trả `view` của phiếu (xem dưới).
	"""
	if not raw and not (department or deliverer_name):
		name = _current_draft(station, receiver)
		return view(_draft(name, station, receiver, lock=False)) if name else None
	if raw:
		employee = _deliverer_from_card(raw)
		values = {
			"department": employee.department,
			"deliverer": employee.name,
			"deliverer_name": employee.employee_name or employee.name,
			"needs_card": 0,
		}
	else:
		values = {
			"department": department,
			"deliverer": None,
			"deliverer_name": _manual_deliverer(department, deliverer_name),
			"needs_card": 1,
		}
	for name in frappe.get_all(
		"Dirty Receipt",
		filters={"receiver": receiver, "station": station, "docstatus": DRAFT, "abandoned": 0},
		pluck="name",
	):
		_abandon(_draft(name, station, receiver))
	doc = frappe.get_doc(
		{
			"doctype": "Dirty Receipt",
			"receiver": receiver,
			"station": station,
			"opened_at": _system_time(client_ts),
			**values,
		}
	)
	doc.flags.tc_receiving = True
	doc.insert(ignore_permissions=True)
	return view(doc)


def _abandon(doc):
	doc.abandoned = 1
	_save(doc)


def discard(receipt, station, receiver):
	"""Bỏ phiếu nháp (giữ bản ghi cho Audit); phiếu đã đóng → RECEIPT_CLOSED."""
	_abandon(_draft(receipt, station, receiver))


# --- Hình dạng trả về cho kiosk ---------------------------------------------------------------------------


def _item_lines(doc, set_unit):
	return [line for line in doc.confirm_lines if line.set_unit == set_unit]


def item_summary(doc, item):
	lines = _item_lines(doc, item.set_unit)
	return {
		"set_id": item.set_unit,
		"set_name": item.set_name,
		"set_type": item.set_type,
		"status_before": item.status_before,
		"bom_version": cint(item.bom_version),
		"confirmed": cint(item.confirmed),
		"needs_review": cint(item.needs_review),
		"forced": cint(item.forced),
		"lines_total": len(lines),
		"lines_confirmed": sum(1 for line in lines if cint(line.confirmed)),
	}


def view(doc):
	"""Phiếu cho kiosk: người giao, khoa, các bộ (tóm tắt) và bộ đang chờ xác nhận (``current``, đủ dòng BOM + ảnh)."""
	items = [item_summary(doc, item) for item in doc.items]
	waiting = next((item for item in doc.items if not cint(item.confirmed)), None)
	return {
		"receipt": doc.name,
		"department": doc.department,
		"department_name": frappe.db.get_value("Department", doc.department, "department_name"),
		"deliverer": doc.deliverer,
		"deliverer_name": doc.deliverer_name,
		"needs_card": cint(doc.needs_card),
		"station": doc.station,
		"opened_at": doc.opened_at,
		"set_count": len(items),
		"flagged_count": sum(1 for item in items if item["needs_review"]),
		"items": items,
		"current": item_detail(doc, waiting) if waiting else None,
	}


def _context(set_type, set_unit, on):
	"""BOM + ảnh áp dụng tại `on` (giờ hệ thống) do M1 trả qua hook; gộp mọi phần trả về."""
	context = {}
	for part in extension.run(
		RECEIPT_CONTEXT_HOOK, {"set_unit": set_unit, "set_type": set_type, "on": on}
	):
		context.update(part)
	return context


def item_detail(doc, item):
	"""Một bộ của phiếu kèm từng dòng BOM (thứ tự BOM, tên, số lượng, ảnh dụng cụ) và ảnh bộ đã xếp (FR-M2-23)."""
	context = _context(item.set_type, item.set_unit, item.received_at)
	media = {line["instrument"]: line for line in context.get("bom", [])}
	lines = [
		{
			"instrument": row.instrument,
			"instrument_name": row.instrument_name,
			"qty": cint(row.qty),
			"position": cint(row.position),
			"confirmed": cint(row.confirmed),
			"thumbnail": (media.get(row.instrument) or {}).get("thumbnail"),
			"image": (media.get(row.instrument) or {}).get("image"),
		}
		for row in sorted(_item_lines(doc, item.set_unit), key=lambda line: (cint(line.position), line.idx))
	]
	return {
		**item_summary(doc, item),
		"lines": lines,
		"tray_images": context.get("tray_images", []),
		"note": item.abnormal_note,
		"photo": item.abnormal_photo,
		"force_reason": item.force_reason,
	}
