"""Kiểm đếm - lắp ráp theo BOM tại T3 (M2, FEAT-020, UC-07, SCR-07).

Dịch vụ trạm T3 (RPC `tracecore.v1.assembly` bọc từng hàm):

- `open_set`: quét Set ID → mở (hoặc mở lại) bản nháp `Assembly Record` của (bộ, chu trình hiện hành) với đủ dòng BOM;
- `line`: ghi một dòng (số lượng thực tế, hỏng/thay, ảnh), quét mã GIAI dụng cụ tự tick (FR-M1-02.2/.4), hoặc "đủ hết";
- `confirm_shortage`: R02 xác nhận đóng gói thiếu bằng PIN proof + lý do (FR-M2-06.1);
- `submit`: ghi sổ chứng từ và ghi cổng T3 qua `core.step_gate` (Đạt, hoặc Không đạt khi rẽ nhánh Sửa chữa/Thanh lý).

M2 không import M1/M8 (lint R1): BOM, ảnh và cơ số đi qua hook ``tracecore_assembly_context``; dụng cụ và mã GIAI đọc
bằng tên DocType. Trạng thái Set Unit chỉ đổi qua `core.step_gate` (cổng T3). Thiếu chưa xác nhận → `submit` bị từ chối
nên cổng T3 vẫn Chưa và T4 khóa bằng chính cổng (A-35 T4). Từ chối nghiệp vụ là `BlockedError` (mã HTTP ở `core.errors`).
"""

import contextlib

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core import audit, client_time, error_codes, extension, gs1, station_auth, step_gate, zones
from tracecore.core.errors import Block, BlockedError

STEP = "T3"  # mã cổng trong step_gate
FUNCTION = "ASSEMBLE"
PACK_FUNCTION = "PACK"
SAVEPOINT = "tc_assembly_submit"
REVIEWER_ROLE = "TC R02"
CONTEXT_HOOK = "tracecore_assembly_context"
NC_HOOK = "tracecore_assembly_nc"
AFTER_HOOK = "tracecore_after_assembly"
BRANCHES = ("Repair", "Disposal")
DISPOSITIONS = ("Repair", "Dispose")
MAX_QTY = 9999
REASON_MAX = 500
SET_FIELDS = tuple(
	"name set_type status cycles_used max_cycles active_cycle_id current_cycle_no is_loaner department".split()
)
SET_TYPE_FIELDS = tuple(
	"name set_type_name method gtin department default_pack_type shelf_life_days tray_image current_bom_version".split()
)
LINE_FIELDS = (
	"instrument instrument_name bom_qty counted actual_qty damaged_qty replaced_qty replacement_instrument "
	"disposition line_status missing_qty photo note"
).split()


def _blocked(code, title, reason, action, items=None, **fields):
	return BlockedError(Block(code, title, reason, action, items=items, **fields))


# --- Trạm, mã quét, bản nháp ---------------------------------------------------------------------


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


def _load_set(raw, for_update=False):
	"""Set Unit từ chuỗi quét `raw` (Set ID GIAI); SCAN_INVALID / SET_NOT_FOUND."""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "set":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code") if scanned["type"] == "unknown" else _("Not a set code"),
			_("Code {0} was not issued by TraceCore.").format(scanned["raw"] or "-")
			if scanned["type"] == "unknown"
			else _("Code {0} is not a Set ID.").format(scanned["id"]),
			_("Scan the Set ID on the set tag."),
		)
	unit = frappe.db.get_value("Set Unit", scanned["id"], SET_FIELDS, as_dict=True, for_update=for_update)
	if not unit:
		raise _blocked(
			"SET_NOT_FOUND",
			_("Set not found"),
			_("Set ID {0} does not exist in TraceCore.").format(scanned["id"]),
			_("Check the set tag or call R02."),
		)
	return unit


def _context(unit, station=None):
	"""Ngữ cảnh T3 từ hook M1/M8 (BOM + ảnh + cơ số); chỉ đọc. `unit` là dict các `SET_FIELDS`."""
	set_type = frappe.db.get_value("Instrument Set Type", unit.set_type, SET_TYPE_FIELDS, as_dict=True)
	ctx = {
		"set_unit": {key: unit[key] for key in SET_FIELDS if key != "department"},
		"set_type": dict(set_type),
		"station": station,
		"receipt_notes": [],
	}
	for part in extension.run(CONTEXT_HOOK, ctx):
		ctx.update(part)
	return ctx


def _draft(name, for_update=False):
	"""Bản nháp `name` của chu trình hiện hành; không có → ASSEMBLY_NOT_FOUND, đã ghi sổ/qua chu trình → ASSEMBLY_CLOSED."""
	row = (
		frappe.db.get_value(
			"Assembly Record",
			name,
			["name", "docstatus", "set_unit", "cycle_no"],
			as_dict=True,
			for_update=for_update,
		)
		if isinstance(name, str) and name
		else None
	)
	if not row:
		raise _blocked(
			"ASSEMBLY_NOT_FOUND",
			_("Assembly record not found"),
			_("Assembly record {0} does not exist.").format(name or "-"),
			_("Scan the Set ID again to open its assembly record."),
		)
	current = cint(frappe.db.get_value("Set Unit", row.set_unit, "current_cycle_no"))
	if cint(row.docstatus) != 0 or cint(row.cycle_no) != current:
		raise _blocked(
			"ASSEMBLY_CLOSED",
			_("Assembly record is closed"),
			_("Assembly record {0} is already recorded or belongs to an earlier cycle.").format(row.name),
			_("Scan the Set ID again to open the assembly record of the current cycle."),
		)
	return frappe.get_doc("Assembly Record", row.name, for_update=for_update)


def _draft_name(unit):
	return frappe.db.get_value(
		"Assembly Record",
		{"set_unit": unit.name, "cycle_no": cint(unit.current_cycle_no), "docstatus": 0},
		"name",
		order_by="creation desc",
		for_update=True,
	)


# --- Mở bộ (FR-M2-05, FR-M2-05.4, FR-M2-25) --------------------------------------------------------


def open_set(raw, station, client_ts=None):
	"""Mở bộ `raw` tại T3 và trả ngữ cảnh kiểm đếm (xem `_summary`); tạo bản nháp nếu chưa có.

	Thứ tự kiểm (trả lỗi đầu tiên gặp): trạm T3 → mã quét → trạng thái Set Unit → cổng T2 Đạt (FR-M2-05.4) → T3 chưa
	Đạt → có BOM. Khóa dòng Set Unit nên hai lần mở cùng bộ chạy lần lượt và chỉ có một bản nháp.
	"""
	_require_station(station)
	unit = _load_set(raw, for_update=True)
	block = step_gate.check(unit.name, STEP, for_update=True)
	if block:
		raise BlockedError(block)
	t3 = next(gate for gate in step_gate.gates(unit.name) if gate["step"] == STEP)
	if t3["result"] == "Pass":
		raise _blocked(
			"STEP_ALREADY_PASSED",
			_("Assembly already recorded"),
			_("Set {0} already passed assembly in cycle {1}.").format(unit.name, cint(unit.current_cycle_no)),
			_("Take the set to the packing station."),
		)
	ctx = _context(unit, station)
	if not ctx.get("bom"):
		raise _blocked(
			"BOM_INCOMPLETE",
			_("Set type has no BOM"),
			_("Set type {0} has no BOM for version {1}.").format(unit.set_type, cint(ctx.get("bom_version"))),
			_("Ask R02 to define the BOM of this set type."),
		)
	name = _draft_name(unit)
	if not name:
		name = (
			frappe.get_doc(
				{
					"doctype": "Assembly Record",
					"set_unit": unit.name,
					"station": station,
					"assembled_by_user": frappe.session.user,
					"client_ts": client_ts,
					"bom_version": cint(ctx.get("bom_version")),
					"lines": [{"instrument": line["instrument"]} for line in ctx["bom"]],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return _summary(frappe.get_doc("Assembly Record", name), ctx)


# --- Ghi dòng (FR-M2-05.1, .2; FR-M1-02.2, .4) ------------------------------------------------------


def _quantity(value, name):
	if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_QTY:
		raise _blocked(
			"QTY_INVALID",
			_("Quantity is not valid"),
			_("{0} must be a whole number from 0 to {1}.").format(_(name), MAX_QTY),
			_("Enter the number of instruments you counted."),
		)
	return value


def _qty_error(reason):
	return _blocked(
		"QTY_INVALID",
		_("Quantity is not valid"),
		reason,
		_("Check the numbers of this line and enter them again."),
	)


def _check_photo(photo):
	if not isinstance(photo, str) or not photo or not frappe.db.exists("File", {"file_url": photo}):
		raise _blocked(
			"PHOTO_INVALID",
			_("Photo could not be attached"),
			_("The file {0} was not uploaded.").format(photo if isinstance(photo, str) else "-"),
			_("Choose the photo again."),
		)


def _check_instrument(code):
	if not isinstance(code, str) or not frappe.db.exists("Instrument", code):
		raise _blocked(
			"INSTRUMENT_NOT_FOUND",
			_("Instrument not found"),
			_("Instrument {0} does not exist.").format(code if isinstance(code, str) else "-"),
			_("Choose an instrument from the spare stock list."),
		)


def line(
	assembly,
	station,
	client_ts=None,
	*,
	instrument=None,
	raw=None,
	actual_qty=None,
	damaged_qty=None,
	replaced_qty=None,
	disposition=None,
	replacement_instrument=None,
	note=None,
	photo=None,
	all_ok=False,
):
	"""Ghi vào bản nháp `assembly`: một dòng (`instrument` + các trường truyền vào), quét mã dụng cụ (`raw`) hoặc đủ hết.

	`actual_qty` đặt thì dòng được tính là đã đếm; `all_ok` đếm mọi dòng chưa đếm đủ theo BOM (nút "Xác nhận tất cả").
	Số lượng sai → ``QTY_INVALID`` (không ghi gì). Trả ngữ cảnh như `open_set`; quét dụng cụ lạ trả thêm ``warning``.
	"""
	_require_station(station)
	doc = _draft(assembly, for_update=True)
	had_shortage = cint(doc.has_shortage)
	extra = {}
	if raw is not None:
		extra = _scan_instrument(doc, raw, station, client_ts)
	elif all_ok:
		for row in doc.lines:
			if not cint(row.counted):
				row.counted, row.actual_qty = 1, cint(row.bom_qty)
	else:
		_apply_line(
			doc,
			instrument,
			{
				"actual_qty": actual_qty,
				"damaged_qty": damaged_qty,
				"replaced_qty": replaced_qty,
				"disposition": disposition,
				"replacement_instrument": replacement_instrument,
				"note": note,
				"photo": photo,
			},
		)
	doc.save(ignore_permissions=True)
	_sync_nc(doc, had_shortage, station, client_ts)
	return {**_summary(doc), **extra}


def _apply_line(doc, instrument, values):
	row = next((r for r in doc.lines if r.instrument == instrument), None)
	if not row:
		raise _blocked(
			"INSTRUMENT_NOT_FOUND",
			_("Instrument not found"),
			_("Instrument {0} is not a line of this BOM.").format(
				instrument if isinstance(instrument, str) else "-"
			),
			_("Scan the Set ID again to reload the BOM."),
		)
	for key in ("actual_qty", "damaged_qty", "replaced_qty"):
		if values[key] is not None:
			_quantity(values[key], key)
	if values["disposition"] is not None and values["disposition"] not in (*DISPOSITIONS, ""):
		raise _qty_error(_("Choose Repair or Dispose for a damaged instrument."))
	if values["replacement_instrument"]:
		_check_instrument(values["replacement_instrument"])
	if values["photo"]:
		_check_photo(values["photo"])
	for key, value in values.items():
		if value is not None:
			row.set(key, value or None if key in ("disposition", "photo", "note") else value)
	if values["actual_qty"] is not None:
		row.counted = 1
	damaged, replaced = cint(row.damaged_qty), cint(row.replaced_qty)
	if replaced > damaged:
		raise _qty_error(
			_("{0}: replaced quantity ({1}) cannot exceed damaged quantity ({2}).").format(
				instrument, replaced, damaged
			)
		)
	if damaged and cint(row.counted) and not row.disposition:
		raise _qty_error(_("{0}: choose Repair or Dispose for the damaged instrument(s).").format(instrument))


def _scan_instrument(doc, raw, station, client_ts):
	"""Quét mã GIAI dụng cụ: tick dòng BOM (+1) hoặc cảnh báo dụng cụ lạ (FR-M1-02.2, .4)."""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "instrument":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} is not an instrument code.").format(scanned["raw"] or "-"),
			_("Scan the code etched on the instrument."),
		)
	if not cint(frappe.db.get_single_value("TraceCore Settings", "enable_instrument_giai")):
		raise _blocked(
			"FEATURE_DISABLED",
			_("Instrument codes are turned off"),
			_("Scanning single instrument codes is not enabled on this site."),
			_("Tick or enter the quantity by hand, or ask R10 to enable instrument codes."),
		)
	code = frappe.db.get_value("Instrument", {"giai_code": scanned["id"]}, "name")
	if not code:
		raise _blocked(
			"INSTRUMENT_NOT_FOUND",
			_("Instrument not found"),
			_("Code {0} is not assigned to any instrument.").format(scanned["id"]),
			_("Check the code on the instrument or count it by hand."),
		)
	row = next((r for r in doc.lines if r.instrument == code), None)
	if row:
		row.counted, row.actual_qty = 1, cint(row.actual_qty) + 1
		return {"scanned": {"instrument": code, "instrument_name": row.instrument_name}}
	known = [item for item in (doc.foreign_instruments or "").split("\n") if item]
	if code not in known:
		doc.foreign_instruments = "\n".join([*known, code])
		doc.flags.tc_new_foreign = code
	return {
		"scanned": {
			"instrument": code,
			"instrument_name": frappe.db.get_value("Instrument", code, "instrument_name"),
		},
		"warning": {
			"code": "FOREIGN_INSTRUMENT",
			"title": _("Foreign instrument"),
			"reason": _("Instrument {0} is not in the BOM of this set.").format(code),
			"action": _("Take it out of the tray and report it; a non-conformance is recorded."),
		},
	}


def _shortage_items(doc):
	return [
		{
			"instrument": row.instrument,
			"instrument_name": row.instrument_name,
			"missing_qty": cint(row.missing_qty),
		}
		for row in doc.lines
		if row.line_status == "Short"
	]


def _sync_nc(doc, had_shortage, station, client_ts):
	"""Cờ NC (A-35 T6): có dòng thiếu hoặc dụng cụ lạ thì ``nc_pending``; hook + Audit khi vừa xuất hiện lần đầu."""
	foreign = [item for item in (doc.foreign_instruments or "").split("\n") if item]
	want = 1 if (cint(doc.has_shortage) or foreign) else 0
	if cint(doc.nc_pending) != want:
		frappe.db.set_value("Assembly Record", doc.name, "nc_pending", want, update_modified=False)
		doc.nc_pending = want
	if cint(doc.has_shortage) and not had_shortage:
		_raise_nc(
			doc,
			"Shortage",
			[item["instrument"] for item in _shortage_items(doc)],
			"AssemblyShortage",
			station,
			client_ts,
		)
	new_foreign = doc.flags.get("tc_new_foreign")
	if new_foreign:
		_raise_nc(doc, "Foreign Instrument", [new_foreign], "AssemblyForeignInstrument", station, client_ts)


def _raise_nc(doc, kind, items, event, station, client_ts):
	audit.log(
		"Update",
		"Assembly Record",
		doc.name,
		new={"event": event, "items": items},
		reason=event,
		station=station,
		client_ts=client_ts,
	)
	extension.run(NC_HOOK, {"assembly": doc.name, "set_unit": doc.set_unit, "kind": kind, "items": items})


# --- Xác nhận thiếu của R02 (FR-M2-06.1, .3; BRU-REP-003) -------------------------------------------


def _reviewer(session, proof):
	"""User R02 đã nhập PIN (PIN proof của phiên `session`); thiếu, sai hoặc không phải R02 → R02_CONFIRM_REQUIRED."""
	reviewer = None
	if proof:
		try:
			reviewer = station_auth.consume_session_pin_proof(session, proof).user
		except BlockedError:
			reviewer = None
	if not reviewer or REVIEWER_ROLE not in frappe.get_roles(reviewer):
		raise _blocked(
			"R02_CONFIRM_REQUIRED",
			_("R02 confirmation required"),
			_("Packing a set with missing instruments needs the PIN of R02."),
			_("Ask R02 to sign in at this station and enter the 6-digit PIN, then confirm again."),
		)
	return reviewer


def _shortage_block(items):
	return Block(
		"SHORTAGE_UNCONFIRMED",
		_("Missing instruments are not confirmed"),
		_("Missing: {0}. Packing stays locked.").format(
			", ".join(f"{item['instrument_name']} ({item['instrument']})" for item in items)
		),
		_("Add the instruments from the spare stock, or ask R02 to confirm with the PIN."),
		items=items,
	)


def confirm_shortage(assembly, reason, station, reviewer_proof=None, session=None, client_ts=None):
	"""R02 xác nhận đóng gói thiếu: lý do 1-500 ký tự + PIN proof của phiên `session`; mở khóa Đóng gói.

	Bản nháp phải đang có dòng thiếu (``NO_SHORTAGE``). Xác nhận gắn với đúng danh sách thiếu lúc đó: đổi số lượng làm
	thiếu khác đi thì xác nhận mất hiệu lực (`AssemblyRecord._guard_confirmation`).
	"""
	_require_station(station)
	doc = _draft(assembly, for_update=True)
	if not cint(doc.has_shortage):
		raise _blocked(
			"NO_SHORTAGE",
			_("Nothing is missing"),
			_("Assembly record {0} has no missing instruments to confirm.").format(doc.name),
			_("Count the lines first; confirm only when instruments are missing."),
		)
	text = (reason or "").strip() if isinstance(reason, str) else ""
	if not text or len(text) > REASON_MAX:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason required"),
			_("Give the reason for packing without the missing instruments ({0} characters at most).").format(
				REASON_MAX
			),
			_("Write the reason, then confirm again."),
		)
	reviewer = _reviewer(session, reviewer_proof)
	doc.flags.tc_assembly = True
	doc.update(
		{
			"shortage_confirmed": 1,
			"shortage_reason": text,
			"shortage_confirmed_by": reviewer,
			"shortage_confirmed_at": now_datetime(),
			"shortage_confirmed_for": doc.shortage_summary,
		}
	)
	doc.save(ignore_permissions=True)
	audit.log(
		"Update",
		"Assembly Record",
		doc.name,
		new={"event": "ShortageConfirmed", "reviewer": reviewer, "items": _shortage_items(doc)},
		reason="AssemblyShortageConfirmed",
		station=station,
		client_ts=client_ts,
	)
	return _summary(doc)


# --- Ghi sổ (FR-M2-06, FR-M2-00.5, FR-M2-25) ----------------------------------------------------------


def submit(assembly, station, client_ts=None, notes=None, branch=None, branch_reason=None):
	"""Ghi sổ bản nháp và ghi cổng T3 trong một savepoint; trả ngữ cảnh đã ghi sổ + ``next_station`` (trạm T4 cùng khu).

	Không rẽ nhánh: mọi dòng phải đã đếm (``LINES_NOT_COUNTED``) và thiếu phải đã R02 xác nhận
	(``SHORTAGE_UNCONFIRMED``) thì cổng T3 Đạt. ``branch`` (``Repair``/``Disposal``) + lý do: cổng T3 Không đạt, bộ về Xử lý
	lại (FR-M2-00.5); Set Unit không đổi trạng thái nào khác (thanh lý chờ FEAT-032). Lỗi giữa chừng hoàn tác về savepoint.
	"""
	client_ts = client_ts or client_time.utc_now()
	client_time.check_skew(client_ts)
	frappe.db.savepoint(SAVEPOINT)
	try:
		return _submit(assembly, station, client_ts, notes, branch, branch_reason)
	except Exception:
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _submit(assembly, station, client_ts, notes, branch, branch_reason):
	_require_station(station)
	doc = _draft(assembly, for_update=True)
	frappe.db.get_value("Set Unit", doc.set_unit, "name", for_update=True)
	if branch and branch not in BRANCHES:
		raise _blocked(
			"BRANCH_INVALID",
			_("Branch is not valid"),
			_("Choose Repair or Disposal for a damaged set."),
			_("Choose one of the two branches, or leave it empty to continue to packing."),
		)
	reason = (branch_reason or "").strip() if isinstance(branch_reason, str) else ""
	if branch and not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason required"),
			_("Give the reason for sending the set to repair or disposal."),
			_("Write the reason, then confirm again."),
		)
	block = step_gate.check(doc.set_unit, STEP, for_update=True)
	if block:
		raise BlockedError(block)
	if not branch:
		uncounted = [row.instrument for row in doc.lines if not cint(row.counted)]
		if uncounted:
			raise _blocked(
				"LINES_NOT_COUNTED",
				_("Not all lines are counted"),
				_("Lines not counted yet: {0}.").format(", ".join(uncounted)),
				_("Tick or enter the quantity of each line, then record the assembly."),
				items=uncounted,
			)
		if cint(doc.has_shortage) and not cint(doc.shortage_confirmed):
			items = _shortage_items(doc)
			# FEAT-052 A-71: DC-001 viện đặt Cảnh báo thì ghi nhận và đi tiếp; nhãn vẫn in dòng THIẾU
			block = error_codes.check(_shortage_block(items))
			if block:
				raise BlockedError(block)
	doc.update(
		{
			"result": "Fail" if branch else "Pass",
			"branch": branch or None,
			"branch_reason": reason or None,
			"client_ts": client_ts,
			"assembled_at": client_time.to_system_time(client_ts),
			"assembled_by_user": frappe.session.user,
			"station": station,
		}
	)
	if notes is not None:
		doc.notes = notes or None
	doc.flags.ignore_permissions = True  # quyền thao tác đã kiểm ở RPC theo role trạm (A-35 T13)
	doc.save()
	doc.submit()
	if branch:
		audit.log(
			"Update",
			"Assembly Record",
			doc.name,
			new={"event": "AssemblyBranch", "branch": branch, "reason": reason},
			reason="AssemblyBranch",
			station=station,
			client_ts=client_ts,
		)
	extension.run(
		AFTER_HOOK,
		{
			"assembly": doc.name,
			"set_unit": doc.set_unit,
			"result": doc.result,
			"branch": doc.branch,
			"branch_reason": doc.branch_reason,
			"station": station,
			"shortage": _shortage_items(doc),
			"damaged": [
				{
					"instrument": row.instrument,
					"damaged_qty": cint(row.damaged_qty),
					"replaced_qty": cint(row.replaced_qty),
					"disposition": row.disposition,
				}
				for row in doc.lines
				if cint(row.damaged_qty)
			],
		},
	)
	result = _summary(doc)
	result["next_station"] = _next_station(station) if doc.result == "Pass" else None
	return result


def _next_station(station):
	"""Trạm đóng gói đang hoạt động cùng khu với `station` (chính nó nếu nó cũng đóng gói), hoặc None."""
	if zones.station_has_function(station, PACK_FUNCTION):
		return station
	zone = frappe.db.get_value("Zone Station", station, "parent_zone")
	found = zones.stations_with_function(PACK_FUNCTION, zone=zone)
	return found[0] if found else None


# --- Ngữ cảnh trả về trạm -----------------------------------------------------------------------------


def _summary(doc, ctx=None):
	"""Ngữ cảnh màn T3 của `doc`: bộ, dòng kiểm đếm kèm ảnh/cơ số, cổng, thiếu/NC, khóa Đóng gói; chỉ đọc."""
	unit = frappe.db.get_value("Set Unit", doc.set_unit, SET_FIELDS, as_dict=True)
	ctx = ctx or _context(unit, doc.station)
	by_code = {line["instrument"]: line for line in ctx.get("bom") or []}
	par = ctx.get("par") or {}
	par_state = {row["instrument"]: row["state"] for row in par.get("instruments") or []}
	lines = []
	for row in doc.lines:
		bom_line = by_code.get(row.instrument, {})
		lines.append(
			{
				**{key: row.get(key) for key in LINE_FIELDS},
				"counted": cint(row.counted),
				"image": bom_line.get("image"),
				"thumbnail": bom_line.get("thumbnail"),
				"position": bom_line.get("position"),
				"par_state": par_state.get(row.instrument),
			}
		)
	lines.sort(key=lambda line: (cint(line["position"]) or 9999, line["instrument"]))
	set_type = ctx["set_type"]
	closed = cint(doc.docstatus) == 1
	passed = closed and doc.result == "Pass"
	uncounted = [line["instrument"] for line in lines if not line["counted"]]
	shortage = _shortage_items(doc)
	if passed:
		lock = None
	elif closed:
		lock = "BRANCH" if doc.branch else "ASSEMBLY_FAILED"
	elif uncounted:
		lock = "LINES_NOT_COUNTED"
	elif cint(doc.has_shortage) and not cint(doc.shortage_confirmed):
		lock = "SHORTAGE_UNCONFIRMED"
	else:
		lock = "NOT_RECORDED"
	return {
		"assembly": doc.name,
		"docstatus": cint(doc.docstatus),
		"result": doc.result,
		"set": {
			"set_id": unit.name,
			"set_type": unit.set_type,
			"set_name": set_type["set_type_name"],
			"method": set_type["method"],
			"status": unit.status,
			"is_loaner": bool(cint(unit.is_loaner)),
			"cycles_used": cint(unit.cycles_used),
			"max_cycles": cint(unit.max_cycles),
		},
		"cycle_no": cint(doc.cycle_no),
		"bom_version": cint(doc.bom_version),
		"lines": lines,
		"tray_image": ctx.get("tray_image"),
		"tray_images": ctx.get("tray_images") or [],
		"gates": step_gate.gates(doc.set_unit),
		"par": ctx.get("par"),
		"receipt_notes": ctx.get("receipt_notes") or [],
		"has_shortage": cint(doc.has_shortage),
		"shortage_items": shortage,
		"shortage_confirmed": cint(doc.shortage_confirmed),
		"shortage_confirmed_by": doc.shortage_confirmed_by,
		"shortage_reason": doc.shortage_reason,
		"nc_pending": cint(doc.nc_pending),
		"foreign_instruments": [item for item in (doc.foreign_instruments or "").split("\n") if item],
		"branch": doc.branch,
		"branch_reason": doc.branch_reason,
		"notes": doc.notes,
		"uncounted": uncounted,
		"ready_to_submit": lock == "NOT_RECORDED",
		"pack_locked": not passed,
		"pack_lock_reason": lock,
	}
