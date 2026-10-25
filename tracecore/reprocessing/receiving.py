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
	"""Khoa chọn được khi người giao không có thẻ (FR-M2-01.7): khoa lá, chưa tắt, theo tên.

	Chỉ khoa đánh dấu `tc_is_ward` (A-22): phòng ban mặc định của ERPNext (Accounts, Sales…) không phải khoa.
	"""
	return frappe.get_all(
		"Department",
		filters={"is_group": 0, "disabled": 0, "tc_is_ward": 1},
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
			_("Card {0} does not belong to an active employee, or it is disabled.").format(
				scanned["raw"] or "-"
			),
			_("Check the card, or choose the department and type the name if the person has no card."),
		)
	if not employee.department:
		raise _blocked(
			"DELIVERER_NO_DEPARTMENT",
			_("Card has no department"),
			_(
				"Employee {0} has no department, so the returning department cannot be taken from the card."
			).format(employee.employee_name or employee.name),
			_("Choose the department and type the name, then ask R02 to complete the employee record."),
		)
	return employee


def _manual_deliverer(department, name):
	row = (
		frappe.db.get_value("Department", department, ["is_group", "disabled"], as_dict=True)
		if department
		else None
	)
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


def view(doc, detail=True):
	"""Phiếu cho kiosk: người giao, khoa, các bộ (tóm tắt) và bộ đang chờ xác nhận (``current``, đủ dòng BOM + ảnh).

	`detail=False` bỏ ``current`` (nơi gọi đã có chi tiết của bộ vừa thao tác, đỡ một lần gọi hook BOM).
	"""
	items = [item_summary(doc, item) for item in doc.items]
	waiting = next((item for item in doc.items if not cint(item.confirmed)), None) if detail else None
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
	for part in extension.run(RECEIPT_CONTEXT_HOOK, {"set_unit": set_unit, "set_type": set_type, "on": on}):
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


# --- Quét bộ (FR-M2-01.1, .2, .5, .6, FR-M2-02, FR-M2-23) -------------------------------------------------


def _not_a_set(scanned, raw):
	"""Mã quét trong phiếu đang mở không phải Set ID: chỉ nhận mã bộ (thẻ người giao đã quét một lần, FR-M2-01.1)."""
	if scanned["type"] == "employee" or _employee_by_card(raw):
		reason = _("A deliverer card was already scanned for this receipt; scan the set tags only.")
	else:
		reason = _("Code {0} is not a Set ID.").format(scanned["raw"] or "-")
	return _blocked(
		"SCAN_INVALID",
		_("Invalid code"),
		reason,
		_("Scan the Set ID on the set tag."),
	)


def _where(set_unit):
	"""Trạm/bước hiện tại của bộ để báo khi từ chối (FR-M2-02.1): trạm đã ghi, hoặc bước đầu tiên chưa Đạt."""
	row = frappe.db.get_value("Set Unit", set_unit, ["current_station", "current_cycle_no"], as_dict=True)
	if row.current_station:
		return row.current_station
	if cint(row.current_cycle_no):
		for gate in step_gate.gates(set_unit):
			if gate["result"] != step_gate.RESULTS[0]:
				return gate["step"]
	return None


def _status_block(set_unit, for_update=False):
	"""Block nếu T1 không nhận bộ (trạng thái không hợp trạm, Hết vòng đời), kèm nơi bộ đang ở; ngược lại None."""
	block = step_gate.check(set_unit, STEP, for_update)
	if block and block.code == "STATUS_INVALID_FOR_STATION":
		where = _where(set_unit)
		if where:
			block.reason = f"{block.reason} " + _("The set is currently at {0}.").format(where)
		block.action = _("Take the set to the station that matches it, or ask R02 to receive it by force.")
	return block


def _approve_force(status, force_reason, session, proof):
	"""``(User R02, lý do)`` cho tiếp nhận cưỡng bức (A-33); không đủ điều kiện → chặn."""
	if status not in FORCE_STATUSES:
		raise _blocked(
			"FORCE_NOT_ALLOWED",
			_("Forced receipt is not allowed"),
			_("A set that is {0} cannot be received by force.").format(_(status, context="Set Unit")),
			_("Ask R01 for an override, or take the set out of circulation."),
		)
	reason = (force_reason or "").strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for receiving this set by force."),
			_("Enter why the set is received although the station refused it."),
		)
	reviewer = None
	if proof:
		with contextlib.suppress(BlockedError):
			reviewer = station_auth.consume_session_pin_proof(session, proof).user
	if not reviewer or REVIEWER_ROLE not in frappe.get_roles(reviewer):
		raise _blocked(
			"R02_CONFIRM_REQUIRED",
			_("R02 confirmation required"),
			_("Only R02 can receive a set that the station refused."),
			_("Ask R02 to sign in at this station and enter the PIN, then scan the set again."),
		)
	return reviewer, reason


def scan_set(
	receipt, raw, station, receiver, client_ts, force_reason=None, session=None, reviewer_proof=None
):
	"""Quét một Set ID vào phiếu nháp `receipt`; trả ``{"duplicate", "item", "summary"}``.

	Chỉ nhận mã bộ; trạng thái phải hợp T1 (`step_gate.check`, FR-M2-02). Bộ đã có trong phiếu → ``duplicate`` và không
	thêm dòng (FR-M2-01.6). `force_reason`/`reviewer_proof` (PIN proof của phiên `session`, R02) chỉ có hiệu lực khi
	bộ bị từ chối (A-33). BOM và ảnh là phiên bản áp dụng tại ngày quét theo giờ hệ thống; chưa ghi gì vào Set Unit.
	`client_ts` là UTC không múi giờ, lệch giờ server quá `client_time.max_skew_seconds()` → ClientTimestampError.
	"""
	client_time.check_skew(client_ts)
	doc = _draft(receipt, station, receiver)
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "set":
		raise _not_a_set(scanned, raw)
	unit = frappe.db.get_value("Set Unit", scanned["id"], ["name", "set_type", "status"], as_dict=True)
	if not unit:
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} does not exist in TraceCore.").format(scanned["raw"] or "-"),
			_("Check the set tag or call R02."),
		)
	existing = next((item for item in doc.items if item.set_unit == unit.name), None)
	if existing:
		return {"duplicate": True, "item": item_detail(doc, existing), "summary": view(doc, detail=False)}
	frappe.db.get_value("Set Unit", unit.name, "name", for_update=True)
	unit.status = frappe.db.get_value("Set Unit", unit.name, "status")
	block = _status_block(unit.name, for_update=True)
	forced = None
	if block:
		if force_reason is None and reviewer_proof is None:
			raise BlockedError(block)
		forced = _approve_force(unit.status, force_reason, session, reviewer_proof)
	on = _system_time(client_ts)
	context = _context(unit.set_type, unit.name, on)
	if not cint(context.get("bom_version")) or not context.get("bom"):
		raise _blocked(
			"BOM_VERSION_NOT_FOUND",
			_("BOM version not found"),
			_("Set type {0} has no effective BOM version.").format(unit.set_type),
			_("Ask R02 to save the BOM of this set type."),
		)
	doc.append(
		"items",
		{
			"set_unit": unit.name,
			"set_type": unit.set_type,
			"set_name": frappe.db.get_value("Instrument Set Type", unit.set_type, "set_type_name"),
			"status_before": unit.status,
			"bom_version": cint(context["bom_version"]),
			"received_at": on,
			"confirmed": 0,
			"forced": 1 if forced else 0,
			"forced_by": forced[0] if forced else None,
			"force_reason": forced[1] if forced else None,
		},
	)
	for line in context["bom"]:
		doc.append(
			"confirm_lines",
			{
				"set_unit": unit.name,
				"instrument": line["instrument"],
				"instrument_name": line["instrument_name"],
				"qty": cint(line["qty"]),
				"position": cint(line["position"]),
				"confirmed": 0,
			},
		)
	_save(doc)
	return {"duplicate": False, "item": item_detail(doc, doc.items[-1]), "summary": view(doc, detail=False)}


# --- Xác nhận thành phần, ghi chú bất thường, ảnh (FR-M2-23.1 đến .6) -----------------------------------------


def _find_item(doc, set_id):
	item = next((row for row in doc.items if row.set_unit == set_id), None)
	if not item:
		raise _blocked(
			"SET_NOT_FOUND",
			_("Set is not on this receipt"),
			_("Set {0} was not scanned into receipt {1}.").format(set_id or "-", doc.name),
			_("Scan the Set ID on the set tag first."),
		)
	return item


def _bom_line_invalid(instrument, set_id):
	return _blocked(
		"BOM_LINE_INVALID",
		_("Component not in the BOM"),
		_("Instrument {0} is not a component of set {1} in the BOM version shown.").format(
			instrument or "-", set_id
		),
		_("Tick only the components listed for the set."),
	)


def _refresh_review(item):
	item.needs_review = 1 if ((item.abnormal_note or "").strip() or item.abnormal_photo) else 0


def confirm_line(
	receipt,
	set_id,
	station,
	receiver,
	lines=None,
	confirm_all=False,
	note=None,
	finalize=False,
	ack_incomplete=False,
):
	"""Cập nhật xác nhận của một bộ trong phiếu nháp; trả ``item_detail``.

	- `lines`: ``[{"instrument", "confirmed"}]`, đặt tick từng dòng; `confirm_all` tick mọi dòng (FR-M2-23.1).
	- `note`: ghi chú bất thường dạng văn bản (None = giữ nguyên, rỗng = xóa); bộ có ghi chú hoặc ảnh mang cờ Cần xem xét
	  (FR-M2-23.2, .3). Không có trường số lượng thực nhận.
	- `finalize`: "Xác nhận bộ". Còn dòng chưa tick và không có ghi chú → CONFIRM_INCOMPLETE (nhắc, FR-M2-23.6) trừ khi
	  `ack_incomplete`. Mọi thay đổi không kèm `finalize` đưa bộ về chưa xác nhận: sửa xong phải Xác nhận bộ lại
	  (FR-M2-23.5). Chưa đổi trạng thái Set Unit (ghi sổ phiếu mới đổi).
	"""
	doc = _draft(receipt, station, receiver)
	item = _find_item(doc, set_id)
	rows = {row.instrument: row for row in _item_lines(doc, item.set_unit)}
	for entry in lines or []:
		row = rows.get(entry.get("instrument"))
		if not row:
			raise _bom_line_invalid(entry.get("instrument"), item.set_unit)
		row.confirmed = 1 if cint(entry.get("confirmed")) else 0
	if confirm_all:
		for row in rows.values():
			row.confirmed = 1
	if note is not None:
		item.abnormal_note = note.strip() or None
	_refresh_review(item)
	item.confirmed = 0
	if finalize:
		pending = [
			f"{row.instrument_name} ({row.instrument})" for row in rows.values() if not cint(row.confirmed)
		]
		if pending and not item.abnormal_note and not ack_incomplete:
			raise _blocked(
				"CONFIRM_INCOMPLETE",
				_("Some components are not confirmed"),
				_("{0} component(s) of set {1} are not ticked and there is no abnormal note.").format(
					len(pending), item.set_unit
				),
				_("Tick the missing components, write an abnormal note, or confirm the set anyway."),
				items=pending,
			)
		item.confirmed = 1
	_save(doc)
	return item_detail(doc, item)


def _photo_invalid(reason):
	return _blocked(
		"PHOTO_INVALID",
		_("Photo is not valid"),
		reason,
		_("Take the photo again (JPEG, PNG or WebP, up to 5 MB)."),
	)


def _checked_image(content_base64):
	"""``(bytes, đuôi file)`` của ảnh bất thường; kiểm theo nội dung, không theo tên file hay Content-Type."""
	import base64
	import binascii

	from PIL import Image, UnidentifiedImageError

	if not isinstance(content_base64, str) or len(content_base64) > PHOTO_MAX_BYTES * 4 // 3 + 16:
		raise _photo_invalid(_("The photo is missing or larger than 5 MB."))
	try:
		data = base64.b64decode(content_base64, validate=True)
	except (binascii.Error, ValueError):
		raise _photo_invalid(_("The photo could not be read.")) from None
	if not data or len(data) > PHOTO_MAX_BYTES:
		raise _photo_invalid(_("The photo is missing or larger than 5 MB."))
	try:
		with Image.open(io.BytesIO(data)) as image:
			extension_ = PHOTO_FORMATS.get(image.format)
			width, height = image.size
			image.verify()
	except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
		raise _photo_invalid(_("The file is not a JPEG, PNG or WebP image.")) from None
	if not extension_ or width * height > PHOTO_MAX_PIXELS:
		raise _photo_invalid(_("The file is not a JPEG, PNG or WebP image."))
	return data, extension_


def attach_photo(receipt, set_id, station, receiver, file_name, content_base64):
	"""Đính ảnh chụp bất thường (tùy chọn) vào một bộ; ảnh riêng tư gắn vào phiếu, thay ảnh cũ nếu có.

	`file_name` chỉ để người dùng nhận ra ảnh, không dùng làm tên file (tên do hệ thống đặt, đuôi theo nội dung).
	Bộ có ảnh mang cờ Cần xem xét. Trả ``item_detail``.
	"""
	doc = _draft(receipt, station, receiver)
	item = _find_item(doc, set_id)
	data, suffix = _checked_image(content_base64)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name}-{frappe.generate_hash(length=8)}.{suffix}",
			"attached_to_doctype": "Dirty Receipt",
			"attached_to_name": doc.name,
			"content": data,
			"is_private": 1,
		}
	)
	file_doc.save(ignore_permissions=True)
	item.abnormal_photo = file_doc.file_url
	_refresh_review(item)
	item.confirmed = 0
	_save(doc)
	return item_detail(doc, item)


# --- Ghi sổ (FR-M2-01.3, .4, FR-M2-23.3, .4, FR-M2-25) ---------------------------------------------------


def _recheck(item):
	"""Block nếu bộ của dòng phiếu không còn tiếp nhận được lúc ghi sổ (đã bị phiếu/trạm khác lấy), ngược lại None."""
	status = frappe.db.get_value("Set Unit", item.set_unit, "status")
	if cint(item.forced):
		if status in step_gate.STATION_STATUSES[STEP] or status in FORCE_STATUSES:
			return None
		return Block(
			"FORCE_NOT_ALLOWED",
			_("Forced receipt is not allowed"),
			_("A set that is {0} cannot be received by force.").format(_(status, context="Set Unit")),
			_("Ask R01 for an override, or take the set out of circulation."),
		)
	return _status_block(item.set_unit, for_update=True)


def _rejection(item, block):
	return {"set_id": item.set_unit, "code": block.code, "reason": block.reason}


def submit(receipt, station, receiver, client_ts):
	"""Ghi sổ phiếu nháp: với từng bộ void Cycle ID chưa dùng, mở chu trình (ghim BOM theo giờ quét, giờ hệ thống) và
	ghi cổng T1 Đạt; bộ → Chờ rửa (``Processing``). Trả ``{"receipt", "sets", "flagged", "rejected", "received_at"}``.

	Mọi bộ phải đã Xác nhận bộ (ITEM_NOT_CONFIRMED). Bộ không còn tiếp nhận được lúc này (bị lấy giữa chừng) bị bỏ khỏi
	phiếu và nằm trong ``rejected`` (``{set_id, code, reason}``); không còn bộ nào → RECEIPT_EMPTY, phiếu vẫn nháp. Mọi
	lỗi hoàn tác về savepoint: không bộ nào đổi trạng thái, phiếu vẫn nháp. `client_ts` là UTC không múi giờ.
	"""
	doc = _draft(receipt, station, receiver)
	if not doc.items:
		raise _blocked(
			"RECEIPT_EMPTY",
			_("Receipt has no sets"),
			_("Receipt {0} has no set to submit.").format(doc.name),
			_("Scan the Set ID of each set before submitting the receipt."),
		)
	waiting = [item.set_unit for item in doc.items if not cint(item.confirmed)]
	if waiting:
		raise _blocked(
			"ITEM_NOT_CONFIRMED",
			_("Some sets are not confirmed"),
			_("{0} set(s) are not confirmed yet.").format(len(waiting)),
			_("Open each set, then press Confirm set."),
			items=waiting,
		)
	frappe.db.savepoint(SAVEPOINT)
	try:
		return _submit(doc, station, client_ts)
	except Exception:
		# Sau deadlock InnoDB đã hoàn tác cả transaction (savepoint không còn): giữ lỗi gốc, bỏ lỗi rollback
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _submit(doc, station, client_ts):
	items = sorted(doc.items, key=lambda item: item.set_unit)
	for item in items:  # khóa theo thứ tự tên: hai phiếu cùng lấy một bộ thì chỉ một nơi giữ được
		frappe.db.get_value("Set Unit", item.set_unit, "name", for_update=True)
	accepted, rejected = [], []
	for item in items:
		block = _recheck(item)
		(rejected if block else accepted).append(_rejection(item, block) if block else item)
	if not accepted:
		raise _blocked(
			"RECEIPT_EMPTY",
			_("No set can be received"),
			_("None of the sets on receipt {0} can be received any more.").format(doc.name),
			_("Check the status of the sets, then scan the sets again."),
			items=rejected,
		)
	dropped = {row["set_id"] for row in rejected}
	if dropped:
		doc.set("items", [item for item in doc.items if item.set_unit not in dropped])
		doc.set("confirm_lines", [line for line in doc.confirm_lines if line.set_unit not in dropped])
	for item in accepted:
		_receive(doc, item, station, client_ts)
	doc.received_at = _system_time(client_ts)
	doc.set_count = len(doc.items)
	doc.flagged_count = sum(1 for item in doc.items if cint(item.needs_review))
	doc.flags.tc_receiving = True
	doc.flags.ignore_permissions = (
		True  # quyền đã kiểm ở RPC (role + phiên trạm); user kiosk không cần quyền ghi sổ Desk
	)
	doc.submit()
	return {
		"receipt": doc.name,
		"sets": [item.set_unit for item in accepted],
		"flagged": [item.set_unit for item in accepted if cint(item.needs_review)],
		"rejected": rejected,
		"received_at": doc.received_at,
	}


def _receive(doc, item, station, client_ts):
	"""Một bộ: hủy Cycle ID chưa dùng → mở chu trình ghim BOM → cổng T1 Đạt (chỉ `core.step_gate` đổi Set Unit)."""
	from frappe.utils import get_datetime

	from tracecore.reprocessing import packing

	active = frappe.db.get_value("Set Unit", item.set_unit, "active_cycle_id")
	item.voided_pack = packing.void_returned_unused(
		active, _("Returned unused at receipt {0}.").format(doc.name)
	)
	# `on` = giờ quét của bộ theo giờ hệ thống (Asia/Ho_Chi_Minh, không múi giờ): đã đổi từ client_ts UTC lúc quét,
	# nên tiếp nhận 00:00-06:59 giờ VN ghim phiên bản BOM của đúng ngày VN (hợp đồng `step_gate.start_cycle`)
	item.cycle_no = step_gate.start_cycle(
		item.set_unit, on=get_datetime(item.received_at), client_ts=client_ts
	)
	step_gate.record(item.set_unit, STEP, "Pass", "Dirty Receipt", doc.name, station, client_ts)
	if cint(item.forced):
		extension.run(
			AFTER_FORCE_HOOK,
			{
				"receipt": doc.name,
				"set_unit": item.set_unit,
				"reason": item.force_reason,
				"by": item.forced_by,
			},
		)
