"""T6 Kho vô khuẩn (FEAT-025, UC-11, FR-M2-13/14): nhập kho theo vị trí, báo rách, hết hạn 00:00, tồn và FEFO.

Pack đi Released → In Sterile Stock (kèm `Pack.location`, mỗi lần nhập/chuyển là một `Sterile Putaway` đã ghi sổ)
→ Void (Expired quá hạn, Torn rách/ướt/mở). Gói Void làm bộ Vô khuẩn sang Chờ tiếp nhận qua
`step_gate.return_to_receipt` (module này không tự đổi trạng thái Set Unit, ADR-005). Khóa theo thứ tự Set Unit rồi
Pack như `packing.void`, để hai thao tác trên một bộ không deadlock.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, now_datetime, today

from tracecore.core import code_registry, error_codes, gs1, step_gate, zones
from tracecore.core.errors import Block, BlockedError

FUNCTION = "PUTAWAY"
EXPIRING_DAYS = 7  # FR-M2-13.2: dashboard kho liệt kê gói hết hạn trong 7 ngày tới
IN_STOCK = "In Sterile Stock"
VOID_EXPIRED = "Expired"
VOID_TORN = "Torn"
SAVEPOINT = "tc_storage_expire"
SUMMARY_FIELDS = ("name", "set_unit", "set_type", "set_name", "expiry", "location", "method")


def _blocked(code, title, reason, action, items=None, **fields):
	return BlockedError(Block(code, title, reason, action, items=items, **fields))


def _require_station(station):
	"""Trạm (không phải khu) có chức năng ``FUNCTION``; ngược lại STATION_WRONG_STEP."""
	row = frappe.db.get_value("Zone Station", station, "is_zone", as_dict=True) if station else None
	if row and not cint(row.is_zone) and zones.station_has_function(station, FUNCTION):
		return
	raise _blocked(
		"STATION_WRONG_STEP",
		_("Wrong station"),
		_("{0} is not a {1} station.").format(station, zones.function_label(FUNCTION))
		if row
		else _("Station {0} does not exist.").format(station or "-"),
		_("Open this screen on a {0} station.").format(zones.function_label(FUNCTION)),
	)


def _scan(raw, kind, title, hint):
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != kind:
		raise _blocked(
			"SCAN_INVALID",
			title,
			_("Code {0} is not valid here.").format(scanned["raw"] or "-"),
			hint,
		)
	return scanned["id"]


def _pack_name(cycle_id):
	name = frappe.db.get_value("Pack", {"name": cycle_id, "docstatus": 1}, "name") if cycle_id else None
	if not name:
		raise _blocked(
			"PACK_NOT_FOUND",
			_("Pack not found"),
			_("Cycle ID {0} does not exist in TraceCore.").format(cycle_id or "-"),
			_("Check the pack label or call R02."),
		)
	return name


def _lock_pack(name):
	"""Khóa Set Unit rồi Pack (cùng thứ tự với `packing.void`); trả Pack."""
	frappe.db.get_value("Set Unit", frappe.db.get_value("Pack", name, "set_unit"), "name", for_update=True)
	return frappe.get_doc("Pack", name, for_update=True)


def _save(pack):
	pack.flags.tc_packing = True  # Pack chỉ cho dịch vụ đóng gói/kho đổi status, void, vị trí sau ghi sổ
	pack.save(ignore_permissions=True)


def _location(code):
	"""Kệ `KE-####` đang dùng; không có → LOCATION_NOT_FOUND (FR-M2-13.5), ngừng dùng → LOCATION_INACTIVE."""
	row = frappe.db.get_value("Sterile Location", code, ["name", "is_active"], as_dict=True)
	if not row:
		raise _blocked(
			"LOCATION_NOT_FOUND",
			_("Location not found"),
			_("Location {0} does not exist.").format(code),
			_("Scan the QR code on the shelf, or ask R10 to create the location."),
		)
	if not cint(row.is_active):
		raise _blocked(
			"LOCATION_INACTIVE",
			_("Location is deactivated"),
			_("Location {0} is deactivated and takes no new packs.").format(code),
			_("Scan another shelf, or ask R10 to activate this one."),
		)
	return row.name


def _summary(pack):
	return {
		"cycle_id": pack["name"],
		"set_id": pack["set_unit"],
		"set_type": pack["set_type"],
		"set_name": pack["set_name"],
		"method": pack["method"],
		"expiry": getdate(pack["expiry"]),
		"location": pack["location"],
	}


def _stock_rows(**filters):
	return frappe.get_all(
		"Pack",
		filters={"docstatus": 1, "status": IN_STOCK, **filters},
		fields=list(SUMMARY_FIELDS),
		order_by="expiry asc, creation asc",
	)


def pack_card(raw):
	"""Thẻ gói cho màn T6 sau khi quét Cycle ID: tóm tắt, trạng thái, kệ hiện tại và năm cổng của bộ.

	Chỉ đọc, không chặn: gói chưa giải phóng hay bộ thiếu cổng vẫn hiện thẻ để KTV thấy lý do; từ chối xảy ra ở
	`putaway` khi quét kệ. Mã không phải gói → SCAN_INVALID; không có gói → PACK_NOT_FOUND.
	"""
	cycle_id = _scan(
		raw, "pack", _("Not a pack code"), _("Scan the DataMatrix or the Cycle ID on the pack label.")
	)
	row = frappe.db.get_value(
		"Pack", _pack_name(cycle_id), [*SUMMARY_FIELDS, "status", "cycle_no"], as_dict=True
	)
	cycle_no = frappe.db.get_value("Set Unit", row.set_unit, "current_cycle_no")
	return {
		**_summary(row),
		"status": row.status,
		"gates": step_gate.gates(row.set_unit) if cint(cycle_no) else [],
	}


# --- Nhập kho và chuyển vị trí (FR-M2-13) ---------------------------------------------------------------


def putaway(pack_raw, location_raw, station, client_ts=None):
	"""Quét Cycle ID rồi mã kệ: gói Released vào kho (Putaway), gói đang trong kho đổi kệ (Move, A2).

	Thứ tự kiểm: trạm T6 → loại mã → gói tồn tại → kệ tồn tại và đang dùng (FR-M2-13.5) → trạng thái gói
	(`PACK_NOT_RELEASED`, FR-M2-13.1) → chưa quá hạn → bộ đủ 5 cổng Đạt (`GATE_PREV_NOT_PASSED` kèm bước thiếu,
	BRU-FLOW-004). Một transaction: Sterile Putaway ghi sổ + Pack (status, location). Trả
	``{"cycle_id", "set_id", "action", "location", "previous_location", "putaway", "status", "expiry"}``.
	"""
	_require_station(station)
	cycle_id = _scan(
		pack_raw, "pack", _("Not a pack code"), _("Scan the DataMatrix or the Cycle ID on the pack label.")
	)
	location_code = _scan(
		location_raw, "location", _("Not a shelf code"), _("Scan the KE- QR code on the shelf.")
	)
	name = _pack_name(cycle_id)
	location = _location(location_code)
	pack = _lock_pack(name)
	if pack.status not in ("Released", IN_STOCK):
		raise _blocked(
			"PACK_NOT_RELEASED",
			_("Pack is not released"),
			_("Pack {0} is {1}; only a released pack can be stored.").format(
				pack.name, _(pack.status, context="Pack")
			),
			_("Check the sterilization load result, or call R02."),
			object_type="Pack",
			object_name=pack.name,
			error_code=error_codes.pack_error_code(pack),
		)
	if getdate(pack.expiry) < getdate(today()):
		raise _blocked(
			"PACK_EXPIRED",
			_("Pack has expired"),
			_("Pack {0} expired on {1}.").format(pack.name, frappe.utils.formatdate(pack.expiry)),
			_("Do not store the pack; send it back to the dirty zone."),
			object_type="Pack",
			object_name=pack.name,
		)
	gate = step_gate.check_stored(pack.set_unit)
	if gate:
		raise BlockedError(gate)
	previous = pack.location if pack.status == IN_STOCK else None
	if pack.status == IN_STOCK and previous == location:
		raise _blocked(
			"PACK_ALREADY_ON_LOCATION",
			_("Pack is already on this shelf"),
			_("Pack {0} is already on location {1}.").format(pack.name, location),
			_("Scan the new shelf to move the pack."),
		)
	action = "Move" if pack.status == IN_STOCK else "Putaway"
	record = frappe.get_doc(
		{
			"doctype": "Sterile Putaway",
			"pack": pack.name,
			"action": action,
			"location": location,
			"from_location": previous if action == "Move" else None,
			"station": station,
			"putaway_by_user": frappe.session.user,
			"putaway_at": now_datetime(),
			"client_ts": client_ts,
		}
	)
	record.flags.tc_storage = True
	record.insert(ignore_permissions=True)
	record.submit()
	pack.update({"status": IN_STOCK, "location": location})
	_save(pack)
	return {
		"cycle_id": pack.name,
		"set_id": pack.set_unit,
		"action": action,
		"location": location,
		"previous_location": previous,
		"putaway": record.name,
		"status": pack.status,
		"expiry": getdate(pack.expiry),
	}


# --- Hết hiệu lực: rách/ướt/mở và quá hạn (FR-M2-14) ------------------------------------------------------


def _void_pack(pack_name, void_reason, note):
	"""Gói trong kho (hoặc đã giải phóng) hết hiệu lực: Void, vô hiệu Cycle ID, bộ Vô khuẩn sang Chờ tiếp nhận."""
	pack = _lock_pack(pack_name)
	pack.update({"status": "Void", "void_reason": void_reason, "void_note": note})
	_save(pack)
	code_registry.disable(pack.name, f"{void_reason}: {note}")
	unit = frappe.db.get_value("Set Unit", pack.set_unit, ["status", "current_cycle_no"], as_dict=True)
	if unit.status == "Sterile" and cint(unit.current_cycle_no) == cint(pack.cycle_no):
		step_gate.return_to_receipt(pack.set_unit)
	return pack


def on_set_status(payload):
	"""Hook ``tracecore_after_set_status``: bộ mượn trả hãng (A-38 e) → gói chưa cấp phát của bộ hết hiệu lực.

	Gói Released / In Sterile Stock → Void ``Returned Unused``, Cycle ID vô hiệu. Trạng thái khác: không làm gì.
	"""
	if payload.get("new_status") != step_gate.RETURNED:
		return
	for name in frappe.get_all(
		"Pack",
		filters={"set_unit": payload["set_unit"], "docstatus": 1, "status": ("in", ("Released", IN_STOCK))},
		pluck="name",
	):
		_void_pack(name, "Returned Unused", _("Loaner set returned to the vendor"))


FORCE_PACK_TARGETS = (IN_STOCK, "Issued", "Used", "Void")  # A-37 b: chuyển tay khi sự cố hệ thống
FORCE_PACK_FROM = ("Released", IN_STOCK, "Issued", "Used")


def force_status(name, status, void_reason=None, note=None):
	"""Chuyển trạng thái gói thủ công (A-37 b, FR-M2-00.3); quyền, lý do, ticket do nơi gọi kiểm.

	Gói đã ghi sổ, đang ``FORCE_PACK_FROM``, tới ``FORCE_PACK_TARGETS`` khác hiện tại; sai → ``ValidationError``.
	Void đi đúng đường hết hiệu lực (vô hiệu Cycle ID, bộ Vô khuẩn sang Chờ tiếp nhận). Trả Pack.
	"""
	pack = _lock_pack(name)
	if (
		pack.docstatus != 1
		or pack.status not in FORCE_PACK_FROM
		or status not in FORCE_PACK_TARGETS
		or status == pack.status
	):
		frappe.throw(
			_("Pack {0} cannot be moved from {1} to {2} by hand.").format(
				pack.name, _(pack.status, context="Pack"), _(status or "-", context="Pack")
			)
		)
	if status == "Void":
		return _void_pack(pack.name, void_reason, note)
	pack.status = status
	_save(pack)
	return pack


def mark_damaged(cycle_id, reason, station, client_ts=None):
	"""Quét báo gói rách/ướt/mở kèm lý do: Pack Void (Torn), bộ sang Chờ tiếp nhận (A1, FR-M2-14).

	Chỉ gói đang trong kho (PACK_NOT_IN_STOCK); lý do bắt buộc (REASON_REQUIRED). Trả
	``{"cycle_id", "set_id", "status", "void_reason"}``.
	"""
	_require_station(station)
	reason = (reason or "").strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for the damaged pack {0}.").format(cycle_id or "-"),
			_("Enter what is wrong with the pack (torn, wet, opened)."),
		)
	name = _pack_name(cycle_id)
	status = frappe.db.get_value("Pack", name, "status", for_update=True)
	if status != IN_STOCK:
		raise _blocked(
			"PACK_NOT_IN_STOCK",
			_("Pack is not in the sterile store"),
			_("Pack {0} is {1}; only a stored pack can be reported damaged here.").format(
				name, _(status, context="Pack")
			),
			_("Check the pack status, or call R02."),
		)
	pack = _void_pack(name, VOID_TORN, reason)
	return {
		"cycle_id": pack.name,
		"set_id": pack.set_unit,
		"status": pack.status,
		"void_reason": pack.void_reason,
	}


def expire_due(on=None):
	"""Việc 00:00 hằng ngày: gói Released / In Sterile Stock có hạn trước ngày `on` (mặc định hôm nay) → Void Expired.

	Hạn là hết ngày `expiry`, nên gói hạn hôm nay còn dùng được và bị đóng lúc 00:00 ngày kế tiếp. Mỗi gói một
	savepoint: gói lỗi được ghi Error Log và bỏ qua, không chặn các gói còn lại. Chạy lại không đổi gì thêm.
	Trả tên (Cycle ID) các gói đã hết hiệu lực.
	"""
	reference = getdate(on or today())
	names = frappe.get_all(
		"Pack",
		filters={"docstatus": 1, "status": ("in", ("Released", IN_STOCK)), "expiry": ("<", reference)},
		pluck="name",
		order_by="expiry asc, name asc",
	)
	expired = []
	for name in names:
		frappe.db.savepoint(SAVEPOINT)
		try:
			pack = frappe.get_doc("Pack", name)
			_void_pack(name, VOID_EXPIRED, _("Expired on {0}").format(frappe.utils.formatdate(pack.expiry)))
		except Exception:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.log_error(title=f"Sterile pack expiry failed: {name}")
		else:
			expired.append(name)
	return expired


def run_expiry():
	"""Điểm vào của scheduler `0 0 * * *`."""
	expire_due()


# --- Tồn, sắp hết hạn, FEFO, danh sách về khu bẩn ---------------------------------------------------------


def overview(on=None):
	"""Dashboard kho (FR-M2-13.2): tồn theo loại bộ, theo vị trí và gói hết hạn trong 7 ngày tới (sớm nhất trước)."""
	reference = getdate(on or today())
	horizon = getdate(add_days(reference, EXPIRING_DAYS))
	rows = _stock_rows()
	by_type, by_location, expiring = {}, {}, []
	names = dict(frappe.get_all("Sterile Location", fields=["name", "location_name"], as_list=True))
	for row in rows:
		expiry = getdate(row.expiry)
		entry = by_type.setdefault(
			row.set_type,
			{"set_type": row.set_type, "set_name": row.set_name, "count": 0, "nearest_expiry": expiry},
		)
		entry["count"] += 1
		entry["nearest_expiry"] = min(entry["nearest_expiry"], expiry)
		place = by_location.setdefault(
			row.location,
			{"location": row.location, "location_name": names.get(row.location), "count": 0},
		)
		place["count"] += 1
		if reference <= expiry <= horizon:
			expiring.append({**_summary(row), "days_left": (expiry - reference).days})
	return {
		"by_set_type": sorted(by_type.values(), key=lambda e: (e["set_name"] or "", e["set_type"])),
		"by_location": sorted(by_location.values(), key=lambda e: e["location"] or ""),
		"expiring": sorted(expiring, key=lambda e: (e["expiry"], e["cycle_id"])),
	}


def fefo_suggest(set_type):
	"""Gói trong kho của `set_type` có hạn sớm nhất còn dùng được (FR-M2-13.3), hoặc None."""
	rows = [row for row in _stock_rows(set_type=set_type) if getdate(row.expiry) >= getdate(today())]
	return _summary(rows[0]) if rows else None


def fefo_check(cycle_id, exclude=()):
	"""Cảnh báo khi còn gói cùng loại bộ hạn gần hơn gói được chọn (FR-M2-13.4); không có thì None.

	Khoa yêu cầu theo Set ID cụ thể vẫn được chấp nhận: nơi cấp phát hiển thị cảnh báo và nhận ghi chú.
	`exclude`: các Cycle ID đã lấy cho cùng phiếu cấp phát (FEAT-026), không tính là còn trong kho.
	"""
	chosen = frappe.db.get_value("Pack", cycle_id, ["set_type", "expiry"], as_dict=True)
	if not chosen:
		return None
	skipped = {cycle_id, *exclude}
	nearer = [
		row
		for row in _stock_rows(set_type=chosen.set_type)
		if getdate(today()) <= getdate(row.expiry) < getdate(chosen.expiry) and row.name not in skipped
	]
	if not nearer:
		return None
	suggested = _summary(nearer[0])
	return {
		"code": "FEFO_NEARER_PACK",
		"title": _("A pack with an earlier expiry is available"),
		"reason": _("Pack {0} expires on {1}, earlier than {2}.").format(
			suggested["cycle_id"], frappe.utils.formatdate(suggested["expiry"]), cycle_id
		),
		"action": _("Take {0} first, or enter a note if the department asked for this Set ID.").format(
			suggested["cycle_id"]
		),
		"suggested": suggested,
	}


def return_list():
	"""Gói hết hiệu lực (quá hạn hoặc rách) mà bộ còn chờ về khu bẩn (FR-M2-14.2), mới nhất trước."""
	return frappe.db.sql(
		"""
		select p.name as cycle_id, p.set_unit as set_id, p.set_type, p.set_name, p.location,
			p.void_reason, p.void_note, p.expiry
		from `tabPack` p
		join `tabSet Unit` s on s.name = p.set_unit and s.current_cycle_no = p.cycle_no
		where p.docstatus = 1 and p.status = 'Void' and p.void_reason in (%s, %s)
			and s.status = 'Awaiting Receipt'
		order by p.modified desc, p.name
		""",
		(VOID_EXPIRED, VOID_TORN),
		as_dict=True,
	)
