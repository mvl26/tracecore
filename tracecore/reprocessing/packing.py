"""Đóng gói tại T4 (M2, FEAT-018, UC-08): quy tắc hạn dùng, lô chỉ thị, BOM; sinh Cycle ID, in lại, hủy, tra cứu.

- Quy tắc (hàm thuần, không ghi): `compute_expiry`, `pack_types`, `resolve_ci_batch`, `missing_lines`.
- Dịch vụ trạm T4 (Task 9 bọc thành RPC): `get_context`, `generate`, `reprint`, `void`, `lookup`;
  nhãn và lệnh in ở `tracecore.reprocessing.pack_label`.

M2 không import `tracecore.instrument`/`tracecore.par` (lint R1): dữ liệu của M1/M8 đi qua hook
(`tracecore.core.extension`, D9) hoặc đọc DocType theo tên. Trạng thái Set Unit chỉ đổi qua `core.step_gate`;
trạng thái gói/số lần in chỉ đổi ở đây (cờ ``flags.tc_packing`` của Pack). Từ chối nghiệp vụ là `BlockedError`.
"""

import contextlib
import math
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, formatdate, get_datetime, getdate, now_datetime
from frappe.utils.data import get_system_timezone

from tracecore.core import client_time, code_registry, extension, gs1, step_gate
from tracecore.core import print as core_print
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import pack_label

CI_CLASSES = ("5", "6")  # FR-M2-07.2: lô chỉ thị loại 5/6 theo phương pháp
SOURCE_PACK_TYPE = "Pack Type"
SOURCE_SET_TYPE = "Set Type"
STEP = "T4"
MAINT_ACTIONS = ("Done", "Deferred")  # option của Pack Maintenance Done.action
# FR-M2-08.5: 10 phút kể từ khi sinh Cycle ID, đo bằng giờ server (D13) từ Pack.creation, số giây nguyên (R3)
REPRINT_WINDOW_SECONDS = 600
SAVEPOINT = "tc_pack_generate"
# ctx["set_unit"] của hook (D9) là các trường này trừ department
SET_FIELDS = tuple(
	"name set_type status cycles_used max_cycles active_cycle_id current_cycle_no is_loaner department".split()
)
SET_TYPE_FIELDS = tuple(
	"name set_type_name method gtin department default_pack_type shelf_life_days tray_image current_bom_version".split()
)
LOOKUP_KEYS = tuple("cycle_id set_id set_name packed_at packer expiry method pack_type ci_batch".split())


def _blocked(code, title, reason, action, items=None):
	return BlockedError(Block(code, title, reason, action, items=items))


# --- Hạn dùng (D4, BRU-REP-009) -----------------------------------------------------------------


def _pack_type_days(item_code):
	"""Hạn lưu (ngày) của loại gói `item_code`; không dùng được làm loại gói → PACK_TYPE_INVALID."""
	row = (
		frappe.db.get_value(
			"Item", item_code, ["tc_item_group_cssd", "tc_shelf_life_days", "disabled"], as_dict=True
		)
		if item_code
		else None
	)
	if not item_code:
		reason = _("No pack type was chosen.")
	elif not row or row.tc_item_group_cssd != "Packaging":
		reason = _("{0} is not a packaging item.").format(item_code)
	elif cint(row.disabled):
		reason = _("Pack type {0} is disabled.").format(item_code)
	elif cint(row.tc_shelf_life_days) <= 0:
		reason = _("Pack type {0} has no shelf life, so the expiry date cannot be calculated.").format(
			item_code
		)
	else:
		return cint(row.tc_shelf_life_days)
	raise _blocked(
		"PACK_TYPE_INVALID",
		_("Pack type cannot be used"),
		reason,
		_("Choose another pack type, or ask R10 to set the shelf life of this one."),
	)


def compute_expiry(packed_on, pack_type, set_type):
	"""Hạn dùng = ngày đóng gói + min(hạn loại gói, hạn ghi đè của loại bộ) (D4).

	Trả ``{"expiry": date, "days": int, "source": "Pack Type" | "Set Type"}``. Loại bộ không ghi đè
	(0/trống) hoặc ghi đè không ngắn hơn hạn loại gói thì nguồn là "Pack Type". Loại gói không phải
	Packaging, đã ngừng dùng hoặc chưa có hạn lưu > 0 thì không dùng được (``PACK_TYPE_INVALID``).
	Số ngày và nguồn trả về là giá trị Task 8 chụp (snapshot) vào Pack.
	"""
	days = _pack_type_days(pack_type)
	source = SOURCE_PACK_TYPE
	override = cint(frappe.db.get_value("Instrument Set Type", set_type, "shelf_life_days"))
	if 0 < override < days:
		days, source = override, SOURCE_SET_TYPE
	return {"expiry": getdate(packed_on) + timedelta(days=days), "days": days, "source": source}


def pack_types(set_type):
	"""Loại gói chọn được cho `set_type`: Item Packaging còn dùng và có hạn lưu > 0.

	Mỗi phần tử là ``{"item", "item_name", "shelf_life_days"}``; loại gói mặc định của loại bộ (nếu còn
	dùng được) đứng đầu, các loại khác theo tên.
	"""
	rows = frappe.get_all(
		"Item",
		filters={"tc_item_group_cssd": "Packaging", "disabled": 0, "tc_shelf_life_days": [">", 0]},
		fields=["name", "item_name", "tc_shelf_life_days"],
		order_by="item_name asc, name asc",
	)
	default = frappe.db.get_value("Instrument Set Type", set_type, "default_pack_type")
	rows.sort(key=lambda row: row.name != default)  # ổn định: mặc định lên đầu, giữ thứ tự tên
	return [
		{"item": row.name, "item_name": row.item_name, "shelf_life_days": cint(row.tc_shelf_life_days)}
		for row in rows
	]


# --- Lô chỉ thị hóa học (BRU-REP-013, BRU-INV-001) ----------------------------------------------


def resolve_ci_batch(raw, method, on_date):
	"""Lô chỉ thị hóa học từ chuỗi quét `raw` cho phương pháp `method`, còn hạn tại ngày `on_date`.

	Làm sạch nhiễu của máy quét (`gs1.clean_scan`), tra Batch không phân biệt hoa/thường và trả tên Batch
	chuẩn: ``{"batch", "item", "expiry_date", "ci_class"}``. Không phải lô chỉ thị loại 5/6 đúng phương pháp,
	không tồn tại, đã ngừng hoặc không có hạn dùng → ``CI_LOT_INVALID``; hết hạn trước `on_date` →
	``CI_LOT_EXPIRED`` (hết hạn đúng ngày `on_date` vẫn dùng được).
	"""
	code = gs1.clean_scan(raw)
	if not code:
		raise _invalid_lot(_("No lot code was scanned."))
	batch = frappe.db.get_value("Batch", code, ["name", "item", "expiry_date", "disabled"], as_dict=True)
	if not batch:
		raise _invalid_lot(_("Lot {0} does not exist.").format(code))
	item = frappe.db.get_value(
		"Item", batch.item, ["tc_item_group_cssd", "tc_compatible_method", "tc_ci_class"], as_dict=True
	)
	if item.tc_item_group_cssd != "Chemical Indicator":
		raise _invalid_lot(_("Lot {0} is not a chemical indicator lot.").format(batch.name))
	if item.tc_ci_class not in CI_CLASSES:
		raise _invalid_lot(
			_("Lot {0} is a class {1} indicator; only class 5 or 6 can be used.").format(
				batch.name, item.tc_ci_class or "-"
			)
		)
	if not item.tc_compatible_method:
		raise _invalid_lot(
			_("The indicator item of lot {0} has no sterilization method set.").format(batch.name)
		)
	if item.tc_compatible_method != method:
		raise _invalid_lot(
			_("Lot {0} is for {1} sterilization, not {2}.").format(
				batch.name, _(item.tc_compatible_method), _(method)
			)
		)
	if cint(batch.disabled):
		raise _invalid_lot(_("Lot {0} has been disabled.").format(batch.name))
	if not batch.expiry_date:
		raise _invalid_lot(_("Lot {0} has no expiry date, so it cannot be checked.").format(batch.name))
	expiry = getdate(batch.expiry_date)
	if expiry < getdate(on_date):
		raise _blocked(
			"CI_LOT_EXPIRED",
			_("Indicator lot has expired"),
			_("Lot {0} expired on {1}.").format(batch.name, formatdate(expiry)),
			_("Scan another indicator lot that is still valid."),
		)
	return {"batch": batch.name, "item": batch.item, "expiry_date": expiry, "ci_class": item.tc_ci_class}


def _invalid_lot(reason):
	return _blocked(
		"CI_LOT_INVALID",
		_("Indicator lot is not valid"),
		reason,
		_("Scan the lot code on a chemical indicator of class 5 or 6 for this sterilization method."),
	)


# --- BOM (BRU-REP-013, FR-M2-07.2) --------------------------------------------------------------


def missing_lines(bom, confirmed):
	"""Các dòng BOM chưa được xác nhận, theo thứ tự BOM.

	`bom` là danh sách dòng từ ``bom.lines`` (mỗi dòng có ``instrument``); `confirmed` là mã dụng cụ đã tick
	(một lần tick phủ cả số lượng của dòng đó).
	"""
	ticked = set(confirmed or ())
	return [line for line in bom if line["instrument"] not in ticked]


def _no_bom(set_type, version):
	"""Loại bộ chưa có dòng BOM ở phiên bản hiện hành: không có gì để đối chiếu nên không sinh Cycle ID."""
	return _blocked(
		"BOM_INCOMPLETE",
		_("Set type has no BOM"),
		_("Set type {0} has no BOM for version {1}.").format(set_type, version),
		_("Ask R02 to define the BOM of this set type."),
	)


def _bom_incomplete(missing):
	return _blocked(
		"BOM_INCOMPLETE",
		_("Not all instruments are confirmed"),
		_("Instruments not confirmed yet: {0}.").format(
			", ".join(f"{line['instrument_name']} ({line['instrument']})" for line in missing)
		),
		_("Check each missing instrument in the tray and tick it, then confirm again."),
		items=[{key: line[key] for key in ("instrument", "instrument_name", "qty")} for line in missing],
	)


# --- Mở bộ tại T4: trạm, mã quét, cổng, GTIN, ngữ cảnh hook ------------------------------------------
# Thứ tự kiểm (Global Constraints): trạm T4 → mã quét → trạng thái Set Unit → Cycle ID hiệu lực → cổng T3 → GTIN
# → cơ số (precheck) → bảo dưỡng → BOM → lô chỉ thị → loại gói. Trả lỗi đầu tiên gặp.


def _require_station(station):
	"""Trạm (không phải khu) của bước T4; ngược lại STATION_WRONG_STEP."""
	row = (
		frappe.db.get_value("Zone Station", station, ["is_zone", "station_step"], as_dict=True)
		if station
		else None
	)
	if row and not cint(row.is_zone) and row.station_step == STEP:
		return
	raise _blocked(
		"STATION_WRONG_STEP",
		_("Wrong station"),
		_("{0} is not a {1} packing station.").format(station, STEP)
		if row
		else _("Station {0} does not exist.").format(station or "-"),
		_("Open the packing screen on a T4 station."),
	)


def _load_set(raw, for_update=False):
	"""Set Unit từ chuỗi quét `raw` (Set ID GIAI); `for_update` khóa dòng. SCAN_INVALID / SET_NOT_FOUND."""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] == "unknown":
		raise _blocked(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} was not issued by TraceCore.").format(scanned["raw"]),
			_("Rescan the set tag or call R02."),
		)
	if scanned["type"] != "set":
		raise _blocked(
			"SCAN_INVALID",
			_("Not a set code"),
			_("Code {0} is not a Set ID.").format(scanned["id"]),
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


def _admit(unit, for_update=False):
	"""Trạng thái Set Unit hợp trạm → chưa có Cycle ID hiệu lực → cổng T3 của chu trình hiện hành Đạt."""
	block = step_gate.check(unit.name, STEP, for_update=for_update)
	if block and block.code == "STATUS_INVALID_FOR_STATION":
		raise BlockedError(block)
	if unit.active_cycle_id:
		raise _blocked(
			"ACTIVE_CYCLE_EXISTS",
			_("Set already has a Cycle ID"),
			_("Set {0} already has Cycle ID {1} in this cycle.").format(unit.name, unit.active_cycle_id),
			_("Reprint the label of {0} within 10 minutes, or void it before packing the set again.").format(
				unit.active_cycle_id
			),
		)
	if block:
		raise BlockedError(block)


def _open(set_id, station, for_update=False, maint_actions=None):
	"""Mở bộ tới hết precheck (cơ số); trả ``(unit, set_type, ctx)``. ``ctx`` là ngữ cảnh hook M1/M8 (D9)."""
	_require_station(station)
	unit = _load_set(set_id, for_update)
	_admit(unit, for_update)
	set_type = frappe.db.get_value("Instrument Set Type", unit.set_type, SET_TYPE_FIELDS, as_dict=True)
	if not gs1.is_valid_gtin14(set_type.gtin):
		raise _blocked(
			"SET_TYPE_GTIN_MISSING",
			_("Set type has no GTIN"),
			_("Set type {0} has no valid GTIN-14, so a Cycle ID cannot be issued.").format(set_type.name),
			_("Ask R10 to enter the GTIN-14 of this set type."),
		)
	ctx = {
		"set_unit": {key: unit[key] for key in SET_FIELDS if key != "department"},
		"set_type": dict(set_type),
		"station": station,
		"maint_actions": list(maint_actions or []),
	}
	for part in extension.run("tracecore_pack_context", ctx):
		ctx.update(part)
	_raise_first("tracecore_pack_prechecks", ctx)
	return unit, set_type, ctx


def _raise_first(hook, ctx):
	for block in extension.run(hook, ctx):
		if block:
			raise BlockedError(block)


def get_context(set_id, station):
	"""Ngữ cảnh màn T4 (SCR-08) cho bộ `set_id` tại `station`; chỉ đọc, không khóa.

	Chặn (BlockedError) như `generate` tới hết precheck cơ số: trạm, mã quét, trạng thái, Cycle ID hiệu lực,
	cổng T3, GTIN loại bộ, cơ số. `label_type` là loại nhãn của máy in sẽ dùng, hoặc loại nhãn cần lắp khi chưa
	có máy in đúng phương pháp (`printer` None). Mỗi loại gói mang thêm `expected_expiry` (ISO) và `days` do server
	tính theo `compute_expiry(hôm nay, loại gói, loại bộ)` để màn T4 không tự tính theo ngày của trình duyệt.
	"""
	unit, set_type, ctx = _open(set_id, station)
	printer = core_print.select_printer(station, set_type.method)
	labels = pack_label.label_items(set_type.method)
	return {
		"set": {
			"set_id": unit.name,
			"set_type": unit.set_type,
			"set_name": set_type.set_type_name,
			"method": set_type.method,
			"is_loaner": bool(cint(unit.is_loaner)),
			"status": unit.status,
			"cycles_used": cint(unit.cycles_used),
			"max_cycles": cint(unit.max_cycles),
			"department": unit.department or set_type.department,
			"is_test": gs1.is_test_gtin(set_type.gtin),
		},
		"gates": step_gate.gates(unit.name),
		"bom": ctx.get("bom", []),
		"bom_version": cint(ctx.get("bom_version")),
		"shortage": [
			{"instrument": row.instrument, "instrument_name": row.instrument_name, "missing_qty": cint(row.missing_qty)}
			for row in confirmed_shortage(unit).values()
		],
		"tray_image": ctx.get("tray_image"),
		"maintenance": ctx.get("maintenance", []),
		"par": ctx.get("par"),
		"pack_types": [_with_expected_expiry(row, set_type.name) for row in pack_types(set_type.name)],
		"ci": {"method": set_type.method, "classes": list(CI_CLASSES)},
		"label_type": printer["label_type"] if printer else (labels[0].name if labels else None),
		"printer": printer,
	}


def _with_expected_expiry(row, set_type):
	"""Loại gói kèm hạn dùng dự kiến nếu đóng gói hôm nay (giờ server, D4)."""
	expiry = compute_expiry(getdate(), row["item"], set_type)
	return {**row, "expected_expiry": str(expiry["expiry"]), "days": expiry["days"]}


# --- Sinh Cycle ID (FR-M2-07/08, BRU-ID-002/004, D13) ------------------------------------------------


def generate(set_id, station, confirmed, ci_batch, pack_type, maint_actions, client_ts):
	"""Sinh Cycle ID cho bộ tại T4 trong MỘT transaction; trả gói, HRI, ảnh DataMatrix và lệnh in.

	`client_ts` là kết quả `parse_client_ts` (UTC, không múi giờ); `packed_at` = giờ hệ thống của nó (D13) và
	quyết định ngày trong Cycle ID, AI (11) và hạn dùng, nên lệch giờ server quá `client_time.max_skew_seconds()`
	→ ClientTimestampError (400) trước khi ghi gì (F1). Khóa Set Unit trước mọi kiểm tra (hai lần sinh cùng bộ
	chạy lần lượt: lần sau gặp ACTIVE_CYCLE_EXISTS). Mọi lỗi (BlockedError hay khác) hoàn tác về savepoint rồi
	ném lại: không còn Pack, dòng Code Registry, số series, cổng T4 hay thay đổi bảo dưỡng nào; Audit Log Reject
	do RPC ghi sau đó. In không bao giờ làm mất Cycle ID (FR-M2-08.8): xem `pack_label.queue_label`.

	Trả ``{"pack": {...}, "hri", "datamatrix_png_b64", "print": {"print_job", "status", "printer", "zpl",
	"warning"}}``; ngày/giờ trong ``pack`` dạng ISO (``YYYY-MM-DD``, ``YYYY-MM-DD HH:MM:SS``), chữ giữ dấu.
	"""
	client_time.check_skew(client_ts)
	frappe.db.savepoint(SAVEPOINT)
	try:
		return _generate(set_id, station, confirmed, ci_batch, pack_type, maint_actions, client_ts)
	except Exception:
		# Sau deadlock, InnoDB đã hoàn tác cả transaction (savepoint không còn): giữ lỗi gốc, bỏ lỗi rollback
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _generate(set_id, station, confirmed, ci_batch, pack_type, maint_actions, client_ts):
	unit, set_type, ctx = _open(set_id, station, for_update=True, maint_actions=maint_actions)
	_raise_first("tracecore_pack_checks", ctx)
	bom = ctx.get("bom") or []
	if not bom:
		raise _no_bom(set_type.name, cint(ctx.get("bom_version")))
	short = confirmed_shortage(unit)  # dòng thiếu đã R02 xác nhận ở T3 (FR-M2-06.1): không phải tick
	missing = missing_lines(bom, [*(confirmed or ()), *short])
	if missing:
		raise _bom_incomplete(missing)
	packed_at = _system_time(client_ts)
	ci = resolve_ci_batch(ci_batch, set_type.method, packed_at.date())
	expiry = compute_expiry(packed_at.date(), pack_type, set_type.name)
	printer = core_print.select_printer(station, set_type.method)

	cycle_id = code_registry.next_cycle_id(packed_at, station)
	pack = frappe.get_doc(
		{
			"doctype": "Pack",
			"set_unit": unit.name,
			"set_type": set_type.name,
			"set_name": set_type.set_type_name,
			"department": unit.department or set_type.department,
			"cycle_no": cint(unit.current_cycle_no),
			"assembly": _assembly(unit),
			"method": set_type.method,
			"bom_version": cint(ctx.get("bom_version")),
			"pack_type": pack_type,
			"ci_batch": ci["batch"],
			"expiry": expiry["expiry"],
			"shelf_life_days_applied": expiry["days"],
			"shelf_life_source": expiry["source"],
			"packed_by_user": frappe.session.user,
			"packed_at": packed_at,
			"client_ts": client_ts,  # ADR-003: thời điểm client lưu UTC
			"station": station,
			"gtin": set_type.gtin,
			"label_type": printer["label_type"] if printer else None,
			"label_print_count": 1,
			"barcode_payload": gs1.make_cycle_payload(
				set_type.gtin, packed_at.date(), expiry["expiry"], cycle_id
			),
			"status": "Packed",
			"instruments_confirmed": _confirmed_rows(bom, short),
			"maint_done": _maint_rows(ctx),
		}
	)
	pack.insert(ignore_permissions=True, set_name=cycle_id)
	pack.submit()
	step_gate.record(unit.name, STEP, "Pass", "Pack", cycle_id, station)
	step_gate.bind_cycle(unit.name, cycle_id, station)
	extension.run("tracecore_after_cycle_id", pack, ctx)
	return pack_label.pack_result(pack, pack_label.queue_label(pack, station, printer))


def _system_time(client_ts):
	"""`client_ts` UTC không múi giờ → giờ hệ thống (Asia/Ho_Chi_Minh) không múi giờ (D13)."""
	utc = get_datetime(client_ts).replace(tzinfo=timezone.utc)
	return utc.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def _assembly(unit):
	"""Chứng từ T3 Đạt mới nhất đã ghi sổ của chu trình hiện hành (R2); T3 ghi không qua chứng từ → None."""
	names = frappe.get_all(
		"Assembly Record",
		filters={
			"set_unit": unit.name,
			"cycle_no": cint(unit.current_cycle_no),
			"docstatus": 1,
			"result": "Pass",
		},
		order_by="creation desc",
		limit=1,
		pluck="name",
	)
	return names[0] if names else None


def confirmed_shortage(unit):
	"""``{mã dụng cụ: dòng}`` của các dòng THIẾU trên phiếu lắp ráp T3 Đạt của chu trình hiện hành mà R02 đã xác nhận.

	Mỗi dòng có ``instrument, instrument_name, actual_qty, missing_qty`` (đọc Assembly Line, FEAT-020). Không có phiếu
	hoặc phiếu không có xác nhận thiếu → ``{}``.
	"""
	name = _assembly(unit)
	if not name or not frappe.db.get_value("Assembly Record", name, "shortage_confirmed"):
		return {}
	rows = frappe.get_all(
		"Assembly Line",
		filters={"parent": name, "parenttype": "Assembly Record", "line_status": "Short"},
		fields=["instrument", "instrument_name", "actual_qty", "missing_qty"],
		order_by="idx asc",
	)
	return {row.instrument: row for row in rows}


def _confirmed_rows(bom, short):
	"""Dòng `Pack.instruments_confirmed`: dòng BOM đủ theo số lượng BOM, dòng thiếu theo số lượng thực có (bỏ nếu 0)."""
	rows = []
	for line in bom:
		qty = cint(short[line["instrument"]].actual_qty) if line["instrument"] in short else line["qty"]
		if qty > 0:
			rows.append({"instrument": line["instrument"], "qty": qty})
	return rows


def _maint_rows(ctx):
	"""Dòng `Pack.maint_done`: nhắc bảo dưỡng đã hiển thị (``ctx["maintenance"]``) có action hợp lệ trong request."""
	actions = {
		action.get("instrument"): action
		for action in ctx.get("maint_actions") or []
		if action.get("action") in MAINT_ACTIONS
	}
	rows = []
	for item in ctx.get("maintenance") or []:
		action = actions.get(item["instrument"])
		if action:
			oil = gs1.clean_scan(action.get("oil_batch"))
			rows.append(
				{
					"instrument": item["instrument"],
					"action": action["action"],
					"oil_batch": frappe.db.get_value("Batch", oil, "name") if oil else None,
					"reason": (action.get("reason") or "").strip() or None,
					"cycles_at_action": cint(item.get("cycles_since")),
				}
			)
	return rows


# --- In lại, hủy, tra cứu (FR-M2-08.5/.6, FR-M2-07.9, BRU-ID-005, AC-10, AC-14) ----------------------


def _pack_name(cycle_id):
	"""Tên Pack đã ghi sổ (= Cycle ID); không có → PACK_NOT_FOUND."""
	name = frappe.db.get_value("Pack", {"name": cycle_id, "docstatus": 1}, "name") if cycle_id else None
	if not name:
		raise _blocked(
			"PACK_NOT_FOUND",
			_("Pack not found"),
			_("Cycle ID {0} does not exist in TraceCore.").format(cycle_id or "-"),
			_("Check the pack label or call R02."),
		)
	return name


def _save_packing(pack):
	pack.flags.tc_packing = True  # Pack chỉ cho dịch vụ đóng gói đổi status/void/số lần in sau ghi sổ
	pack.save(ignore_permissions=True)


def reprint(cycle_id, reason, station):
	"""In lại nhãn cùng Cycle ID trong 10 phút kể từ khi sinh (AC-10); trả cùng dạng `generate`.

	Cửa sổ đo bằng giờ server từ `Pack.creation` (lúc server sinh Cycle ID), không từ `packed_at` (giờ client, có
	thể lệch). Lý do trống → REASON_REQUIRED; gói không còn Packed → STATUS_INVALID_FOR_STATION; nhãn còn chờ in
	(Print Job Waiting) → trả lại job đó kèm cảnh báo ``LABEL_ALREADY_WAITING``, không tạo job, không tăng số lần in;
	quá 600 s (số giây nguyên, R3) → REPRINT_WINDOW_EXPIRED. `label_print_count + 1`; Print Job mới mang
	`reprint_reason`.
	"""
	_require_station(station)
	reason = (reason or "").strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for reprinting the label of {0}.").format(cycle_id or "-"),
			_("Enter why the label must be printed again."),
		)
	pack = frappe.get_doc("Pack", _pack_name(cycle_id), for_update=True)
	if pack.status != "Packed":
		raise _blocked(
			"STATUS_INVALID_FOR_STATION",
			_("Label cannot be reprinted"),
			_("Pack {0} is {1}; only the label of a packed pack can be reprinted.").format(
				pack.name, _(pack.status, context="Pack")
			),
			_("Scan the label of a pack that is still packed, or call R02."),
		)
	waiting = pack_label.waiting_label(pack)
	if waiting:
		return pack_label.pack_result(pack, waiting)
	elapsed = math.floor((now_datetime() - get_datetime(pack.creation)).total_seconds())
	if elapsed > REPRINT_WINDOW_SECONDS:
		raise _blocked(
			"REPRINT_WINDOW_EXPIRED",
			_("Reprint window has passed"),
			_(
				"Cycle ID {0} was issued {1} minutes ago; a label can be reprinted only within 10 minutes."
			).format(pack.name, elapsed // 60),
			_("Void the Cycle ID and pack the set again."),
		)
	pack.label_print_count = cint(pack.label_print_count) + 1
	_save_packing(pack)
	printer = core_print.select_printer(station, pack.method)
	return pack_label.pack_result(pack, pack_label.queue_label(pack, station, printer, reprint_reason=reason))


def void(cycle_id, reason, station, note=None):
	"""Hủy hiệu lực Cycle ID tại T4 (D12): gói Void, mã bị vô hiệu trong Code Registry, cổng T4 Không đạt.

	`reason` phải là một option `void_reason` của Pack (REASON_REQUIRED); chỉ gói Packed (PACK_NOT_VOIDABLE).
	Nhãn còn chờ in (Print Job Waiting) của gói chuyển Failed để `set_roll` không bao giờ in mã đã hủy.
	T4 Fail (``redo_count + 1``, Set Unit → Reprocess) khi gói thuộc chu trình hiện hành của bộ; bỏ Cycle ID hiện
	hành của bộ khi đó chính là mã bị hủy. Trả ``{"cycle_id", "set_id", "status", "void_reason"}``.
	"""
	_require_station(station)
	reasons = [o for o in (frappe.get_meta("Pack").get_field("void_reason").options or "").split("\n") if o]
	if reason not in reasons:
		raise _blocked(
			"REASON_REQUIRED",
			_("Void reason is required"),
			_("{0} is not a valid void reason.").format(reason)
			if reason
			else _("No void reason was chosen."),
			_("Choose why the Cycle ID is voided."),
		)
	name = _pack_name(cycle_id)
	# khóa Set Unit rồi mới tới Pack: cùng thứ tự với generate nên hai thao tác trên một bộ không deadlock
	unit = frappe.db.get_value(
		"Set Unit",
		frappe.db.get_value("Pack", name, "set_unit"),
		["name", "current_cycle_no", "active_cycle_id"],
		as_dict=True,
		for_update=True,
	)
	pack = frappe.get_doc("Pack", name, for_update=True)
	if pack.status != "Packed":
		raise _blocked(
			"PACK_NOT_VOIDABLE",
			_("Pack cannot be voided"),
			_("Pack {0} is {1}; only a packed pack can be voided at T4.").format(
				pack.name, _(pack.status, context="Pack")
			),
			_("Check the pack status, or call R02."),
		)
	note = (note or "").strip() or None
	pack.update({"status": "Void", "void_reason": reason, "void_note": note})
	_save_packing(pack)
	code_registry.disable(pack.name, f"{reason}: {note}" if note else reason)
	pack_label.cancel_waiting_jobs(pack, reason)
	if cint(unit.current_cycle_no) == cint(pack.cycle_no):
		step_gate.record(unit.name, STEP, "Fail", "Pack", pack.name, station)
	if unit.active_cycle_id == pack.name:
		step_gate.release_cycle(unit.name)
	return {"cycle_id": pack.name, "set_id": unit.name, "status": pack.status, "void_reason": reason}


def lookup(raw):
	"""Tra cứu gói từ chuỗi quét: DataMatrix/HRI của nhãn hoặc Cycle ID trần (AC-14, FR-M2-07.9).

	Không phải mã gói → SCAN_INVALID; không có gói đã ghi sổ → PACK_NOT_FOUND. Ngày/giờ dạng ISO như `generate`.
	"""
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "pack":
		raise _blocked(
			"SCAN_INVALID",
			_("Not a pack code"),
			_("Code {0} is not a pack label or Cycle ID.").format(scanned["raw"] or "-"),
			_("Scan the DataMatrix or the Cycle ID on the pack label."),
		)
	pack = frappe.get_doc("Pack", _pack_name(scanned["id"]))
	summary = pack_label.pack_summary(pack)
	return {
		**{key: summary[key] for key in LOOKUP_KEYS},
		"status": pack.status,
		"label_print_count": cint(pack.label_print_count),
	}
