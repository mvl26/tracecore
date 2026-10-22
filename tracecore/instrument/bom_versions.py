"""Phiên bản BOM của loại bộ (M1, FEAT-015; FR-M1-03, .1, .3, .6, FR-M1-04, .4; OTH-RET-002; S1, S2, S4, S5, S13, S14).

Mô hình (S1): không có DocType phiên bản. Một phiên bản = các dòng ``Set BOM Item`` cùng (``set_type``, ``bom_version``);
mọi dòng của phiên bản mang cùng ``effective_from``, ``change_reason``, ``based_on_version``. Phiên bản **bất biến** sau
khi lưu (chốt ở ``SetBOMItem.validate``); mọi dòng chỉ được tạo ở module này (cờ ``flags.tc_bom``).

Ngày hiệu lực (S2): kiểu Date theo múi giờ hệ thống ``Asia/Ho_Chi_Minh`` (``nowdate``, không dùng ``date.today()`` của
tiến trình), hiệu lực từ 00:00. Phiên bản áp dụng tại ngày D = ``max(bom_version)`` có ``effective_from ≤ D``; cùng một
ngày thì số lớn thắng, phiên bản thua không bao giờ áp dụng ("Bị thay trước hiệu lực"). ``current_bom_version`` của loại
bộ chỉ là giá trị suy ra (server ghi khi phiên bản hiệu lực ngay và bởi scheduler ``roll_effective_versions`` lúc 00:00);
nơi đọc dùng ``effective_version`` tính trực tiếp từ dòng nên đúng cả khi scheduler trễ.

Tạo phiên bản (S4): copy-on-edit — gửi toàn bộ dòng của phiên bản mới cùng ``base_version`` (phiên bản người dùng đang
xem). Khóa dòng loại bộ (``for update``) rồi đọc phiên bản mới nhất bằng **locking read** (REPEATABLE READ: đọc thường
có thể trả snapshot cũ từ đầu transaction): khác ``base_version`` → ``BOM_VERSION_CONFLICT``. Unique (``set_type``,
``bom_version``, ``instrument``) là chốt cuối.

Luật dòng (S5): dụng cụ tồn tại, ``Active``, họ phương pháp của loại bộ thuộc họ phương pháp của dụng cụ (``Steam`` /
``Plasma``, không phân biệt 121/134 °C), ``qty`` nguyên 1-999, không trùng dụng cụ, không trùng thứ tự xếp gửi lên
(server đánh lại 1..n), tối đa 500 dòng; mọi lỗi trả cùng lúc theo từng dòng.
"""

import math
import re
from collections import defaultdict
from datetime import date, datetime

import frappe
from frappe import _
from frappe.utils import cint, cstr, escape_html, formatdate, getdate, nowdate

from tracecore.core import audit
from tracecore.core.errors import Block, BlockedError
from tracecore.instrument import catalog

ITEM = "Set BOM Item"
SET_TYPE = "Instrument Set Type"
MAX_LINES = 500
MAX_QTY = 999
REASON_MAX = 500
STATUS_EFFECTIVE = "Effective"
STATUS_SCHEDULED = "Scheduled"
STATUS_SUPERSEDED = "Superseded"
STATUS_SKIPPED = "Skipped"
SCHEDULED_REASON = "scheduled"  # cột reason của Audit Log khi scheduler kích hoạt phiên bản (S14)
# phần đầu nhận khi tạo loại bộ (ảnh khay đi qua luật file riêng, Task 5); current_bom_version do server đặt
HEADER_FIELDS = (
	"type_code",
	"set_type_name",
	"method",
	"department",
	"default_pack_type",
	"shelf_life_days",
	"is_implant",
	"assembly_minutes",
	"gtin",
)
# sao chép loại bộ (UC-02 A2, S13): phần đầu trừ mã, tên, GTIN, ảnh
COPY_FIELDS = (
	"method",
	"department",
	"default_pack_type",
	"shelf_life_days",
	"is_implant",
	"assembly_minutes",
)
SAVEPOINT = "tc_bom_version"
_INTEGER = re.compile(r"-?[0-9]+")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NO_DATE = date.min  # dòng cũ chưa có ngày hiệu lực: coi như hiệu lực từ đầu


def today() -> date:
	"""Hôm nay theo múi giờ hệ thống (Asia/Ho_Chi_Minh), không theo giờ của tiến trình."""
	return getdate(nowdate())


# --- Dòng BOM -------------------------------------------------------------------------------------------------


def whole_number(value) -> int | None:
	"""Số nguyên từ int, float không có phần lẻ hoặc chuỗi chữ số; còn lại (kể cả bool) → None."""
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		return int(value) if value.is_integer() else None
	if isinstance(value, str) and _INTEGER.fullmatch(value.strip()):
		return int(value.strip())
	return None


def normalize_lines(lines) -> list[dict]:
	"""Chuẩn hóa dòng gửi lên: ``[{row, instrument, qty, position, …}]`` theo thứ tự xếp.

	``row`` = số thứ tự dòng như người dùng gửi (1..n, dùng trong thông báo lỗi); ``instrument`` = mã chuẩn
	(``catalog.clean_code``, None khi sai định dạng); ``qty`` = số nguyên hoặc None khi không phải số nguyên;
	``position`` = 1..n sau khi sắp theo thứ tự xếp gửi lên (thiếu thì theo thứ tự gửi). Không kiểm luật (xem
	``line_errors``); ``lines`` không phải list các object → ``frappe.ValidationError``.
	"""
	lines = [] if lines is None else lines
	if not isinstance(lines, list) or not all(isinstance(line, dict) for line in lines):
		frappe.throw(_("BOM lines must be a list of objects with instrument, qty and position."))
	rows = []
	for index, line in enumerate(lines, 1):
		raw_position = line.get("position")
		given = None if raw_position in (None, "") else whole_number(raw_position)
		rows.append(
			{
				"row": index,
				"instrument": catalog.clean_code(line.get("instrument")),
				"raw_instrument": cstr(line.get("instrument"))[: catalog.CODE_MAX_LENGTH * 2],
				"qty": whole_number(line.get("qty")),
				"given_position": given if given is not None and given >= 1 else None,
				"position_invalid": raw_position not in (None, "") and (given is None or given < 1),
			}
		)
	rows.sort(key=lambda row: (row["given_position"] or math.inf, row["row"]))
	for position, row in enumerate(rows, 1):
		row["position"] = position
	return rows


def _instrument_facts(codes: list[str], lock: bool) -> tuple[dict, dict]:
	"""``({mã: trạng thái}, {mã: {phương pháp}})`` bằng hai truy vấn cố định.

	``lock``: đọc dụng cụ bằng ``lock in share mode`` (đọc bản mới nhất đã commit và chặn ngừng sử dụng song song tới
	khi phiên bản được lưu).
	"""
	if not codes:
		return {}, {}
	marks = ", ".join(["%s"] * len(codes))
	share = " lock in share mode" if lock else ""
	statuses = dict(
		frappe.db.sql(f"select name, status from `tabInstrument` where name in ({marks}){share}", codes)  # nosec B608
	)
	methods = defaultdict(set)
	for parent, method in frappe.db.sql(
		f"""
		select parent, method from `tabInstrument Compatible Method`
		where parenttype = 'Instrument' and parentfield = 'compatible_methods' and parent in ({marks})
		""",  # nosec B608 - chỉ chèn chuỗi giữ chỗ %s
		codes,
	):
		methods[parent].add(method)
	return statuses, methods


def line_errors(method: str | None, lines: list[dict], lock: bool = False) -> list[dict]:
	"""Lỗi của các dòng đã chuẩn hóa (``normalize_lines``) với phương pháp loại bộ `method`.

	Mỗi lỗi ``{row, instrument, code, message}``, ``code`` ∈ ``NOT_FOUND``, ``RETIRED``, ``INCOMPATIBLE``,
	``DUPLICATE_INSTRUMENT``, ``DUPLICATE_POSITION``, ``POSITION_INVALID``, ``QTY_RANGE``; một dòng có thể có nhiều lỗi;
	sắp theo dòng gửi lên. ``method`` trống → bỏ kiểm tương thích (thiếu phương pháp do kiểm bắt buộc của loại bộ báo).
	"""
	statuses, methods = _instrument_facts(
		sorted({row["instrument"] for row in lines if row["instrument"]}), lock
	)
	errors, first_row, first_position = [], {}, {}
	for row in sorted(lines, key=lambda line: line["row"]):
		code = row["instrument"]
		label = code or row.get("raw_instrument") or "-"

		def add(error_code, message, row=row, label=label):
			errors.append({"row": row["row"], "instrument": label, "code": error_code, "message": message})

		if not code or code not in statuses:
			add("NOT_FOUND", _("Instrument {0} not found.").format(label))
		else:
			if statuses[code] == "Retired":
				add("RETIRED", _("Instrument {0} is retired and cannot be added to a BOM.").format(code))
			if method and method not in catalog.families(methods[code]):
				add(
					"INCOMPATIBLE",
					_("Instrument {0} ({1}) is not compatible with the set type method {2}.").format(
						code, ", ".join(catalog.ordered_methods(methods[code])) or "—", _(method)
					),
				)
			if code in first_row:
				add(
					"DUPLICATE_INSTRUMENT",
					_(
						"Instrument {0} is already listed in row {1}. Combine the quantities in one line."
					).format(code, first_row[code]),
				)
			else:
				first_row[code] = row["row"]
		if row.get("position_invalid"):
			add("POSITION_INVALID", _("Position must be a whole number of at least 1."))
		elif row.get("given_position") is not None:
			position = row["given_position"]
			if position in first_position:
				add(
					"DUPLICATE_POSITION",
					_("Position {0} is already used in row {1}.").format(position, first_position[position]),
				)
			else:
				first_position[position] = row["row"]
		if row["qty"] is None or not 1 <= row["qty"] <= MAX_QTY:
			add("QTY_RANGE", _("Quantity must be a whole number from 1 to {0}.").format(MAX_QTY))
	return errors


# --- Từ chối nghiệp vụ -------------------------------------------------------------------------------------------


def not_found_block(set_type) -> Block:
	return Block(
		"SET_TYPE_NOT_FOUND",
		_("Set type not found"),
		_("Set type {0} not found.").format(set_type if isinstance(set_type, str) and set_type else "-"),
		_("Check the set type code."),
	)


def code_exists_block(type_code) -> Block:
	return Block(
		"SET_TYPE_CODE_EXISTS",
		_("Set type code already used"),
		_("Set type {0} already exists.").format(type_code),
		_("Enter a different type code."),
	)


def _empty_block() -> Block:
	return Block(
		"BOM_EMPTY",
		_("BOM is empty"),
		_("A set type needs at least one BOM line."),
		_("Add the instruments of the set, then save."),
	)


def _too_large_block(count: int) -> Block:
	return Block(
		"BOM_TOO_LARGE",
		_("BOM too large"),
		_("The BOM has {0} lines; at most {1} are allowed.").format(count, MAX_LINES),
		_("Split the set into smaller set types."),
	)


def _lines_block(items: list[dict]) -> Block:
	return Block(
		"BOM_LINE_INVALID",
		_("BOM not saved"),
		_("{0} BOM lines have errors.").format(len({item["row"] for item in items})),
		_("Fix the lines listed below, then save again."),
		items=items,
	)


def _date_block(reason: str) -> Block:
	return Block(
		"BOM_EFFECTIVE_DATE_INVALID",
		_("Effective date not accepted"),
		reason,
		_("Choose today or a later date, not earlier than the latest BOM version."),
	)


def _reason_block(reason: str) -> Block:
	return Block(
		"REASON_REQUIRED",
		_("Reason is required"),
		reason,
		_("Enter why the BOM changes, at most {0} characters.").format(REASON_MAX),
	)


def _rows_or_block(lines) -> list[dict]:
	rows = normalize_lines(lines)
	if not rows:
		raise BlockedError(_empty_block())
	if len(rows) > MAX_LINES:
		raise BlockedError(_too_large_block(len(rows)))
	return rows


# --- Đọc phiên bản -----------------------------------------------------------------------------------------------


def _max_effective(set_type: str, day: date, lock: bool = False) -> int | None:
	value = frappe.db.sql(
		f"""
		select max(bom_version) from `tabSet BOM Item`
		where set_type = %s and (effective_from is null or effective_from <= %s){" for update" if lock else ""}
		""",  # nosec B608 - chỉ chèn hằng
		(set_type, day),
	)[0][0]
	return cint(value) or None


def effective_version(set_type: str, on=None) -> int | None:
	"""Phiên bản áp dụng tại ngày `on` (mặc định hôm nay giờ hệ thống) = số lớn nhất có ``effective_from ≤ on``.

	None khi loại bộ chưa có phiên bản nào hiệu lực. Tính trực tiếp từ dòng (không đọc ``current_bom_version``).
	"""
	return _max_effective(set_type, getdate(on) if on else today())


def _dates_by_set_type(set_types) -> dict[str, dict[int, date]]:
	result: dict[str, dict[int, date]] = defaultdict(dict)
	set_types = sorted(set_types)
	if not set_types:
		return result
	marks = ", ".join(["%s"] * len(set_types))
	for set_type, version, day in frappe.db.sql(
		f"""
		select set_type, bom_version, min(effective_from)
		from `tabSet BOM Item` where set_type in ({marks})
		group by set_type, bom_version
		""",  # nosec B608 - chỉ chèn chuỗi giữ chỗ %s
		set_types,
	):
		result[set_type][cint(version)] = getdate(day) if day else _NO_DATE
	return result


def _statuses(dates: dict[int, date], on: date) -> dict[int, str]:
	"""Trạng thái từng phiên bản tại ngày `on` (S2).

	Bị thay trước hiệu lực: có phiên bản số lớn hơn với ngày ≤ ngày của nó (không bao giờ áp dụng ngày nào). Còn lại:
	phiên bản áp dụng hôm nay → Đang hiệu lực; ngày sau `on` → Đã lên lịch; trước đó → Đã thay thế.
	"""
	effective = max((version for version, day in dates.items() if day <= on), default=None)
	result = {}
	for version, day in dates.items():
		if any(other > version and other_day <= day for other, other_day in dates.items()):
			result[version] = STATUS_SKIPPED
		elif version == effective:
			result[version] = STATUS_EFFECTIVE
		elif day > on:
			result[version] = STATUS_SCHEDULED
		else:
			result[version] = STATUS_SUPERSEDED
	return result


def live_map(set_types, on=None) -> dict[str, dict]:
	"""``{loại bộ: {"effective": int | None, "scheduled": [phiên bản đã lên lịch, tăng dần]}}`` (một truy vấn).

	Phiên bản bị thay trước hiệu lực không tính (kể cả khi số lớn hơn vượt lên ở ngày sớm hơn).
	"""
	on = getdate(on) if on else today()
	result = {}
	for set_type, dates in _dates_by_set_type(set_types).items():
		statuses = _statuses(dates, on)
		effective = [version for version, status in statuses.items() if status == STATUS_EFFECTIVE]
		result[set_type] = {
			"effective": effective[0] if effective else None,
			"scheduled": sorted(
				version for version, status in statuses.items() if status == STATUS_SCHEDULED
			),
		}
	return result


def live_versions(set_type: str, on=None) -> list[int]:
	"""Phiên bản còn áp dụng từ ngày `on`: phiên bản hiệu lực (nếu có) rồi các phiên bản đã lên lịch (tăng dần)."""
	live = live_map([set_type], on).get(set_type) or {"effective": None, "scheduled": []}
	return ([live["effective"]] if live["effective"] else []) + live["scheduled"]


def versions(set_type: str) -> list[dict]:
	"""Các phiên bản BOM của loại bộ, mới → cũ (một truy vấn).

	Mỗi phiên bản ``{bom_version, effective_from, reason, based_on_version, created_by, created_on, line_count,
	total_qty, status}``; ``status`` ∈ ``Effective``, ``Scheduled``, ``Superseded``, ``Skipped`` tính tại hôm nay.
	"""
	rows = frappe.db.sql(
		"""
		select bom_version, min(effective_from) as effective_from, max(change_reason) as reason,
			max(based_on_version) as based_on_version, max(owner) as created_by, min(creation) as created_on,
			count(*) as line_count, sum(qty) as total_qty
		from `tabSet BOM Item`
		where set_type = %s
		group by bom_version
		order by bom_version desc
		""",
		(set_type,),
		as_dict=True,
	)
	statuses = _statuses(
		{
			cint(row.bom_version): getdate(row.effective_from) if row.effective_from else _NO_DATE
			for row in rows
		},
		today(),
	)
	return [
		{
			"bom_version": cint(row.bom_version),
			"effective_from": getdate(row.effective_from) if row.effective_from else None,
			"reason": row.reason,
			"based_on_version": cint(row.based_on_version),
			"created_by": row.created_by,
			"created_on": row.created_on,
			"line_count": cint(row.line_count),
			"total_qty": cint(row.total_qty),
			"status": statuses[cint(row.bom_version)],
		}
		for row in rows
	]


def _version_lines(set_type: str, version: int, lock: bool = False) -> list[tuple[str, int]]:
	"""``[(mã dụng cụ, số lượng)]`` của một phiên bản theo thứ tự xếp."""
	return [
		(instrument, cint(qty))
		for instrument, qty in frappe.db.sql(
			f"""
			select instrument, qty from `tabSet BOM Item`
			where set_type = %s and bom_version = %s
			order by position asc, name asc{" for update" if lock else ""}
			""",  # nosec B608 - chỉ chèn hằng
			(set_type, cint(version)),
		)
	]


# --- Ghi --------------------------------------------------------------------------------------------------------


def _insert_lines(set_type: str, version: int, rows: list[dict], effective_from, reason: str, based_on: int):
	for row in rows:
		doc = frappe.get_doc(
			{
				"doctype": ITEM,
				"set_type": set_type,
				"bom_version": version,
				"instrument": row["instrument"],
				"qty": row["qty"],
				"position": row["position"],
				"effective_from": effective_from,
				"change_reason": reason,
				"based_on_version": based_on,
			}
		)
		doc.flags.tc_bom = True
		# quyền: RPC đã kiểm role R02/R10/SM; Set BOM Item không cho ai tạo trực tiếp (S12)
		doc.insert(ignore_permissions=True)


def create_set_type(header: dict, lines: list[dict], reason: str | None = None) -> str:
	"""Tạo loại bộ cùng BOM phiên bản 1 trong một transaction (FR-M1-03, .1, .3, .6); trả mã loại bộ.

	v1: ``effective_from`` = hôm nay, ``change_reason`` = "Initial version" (hoặc `reason`, vd khi sao chép),
	``based_on_version`` = 0; ``current_bom_version`` = 1. Từ chối (``BlockedError``, không ghi gì): ``BOM_EMPTY``,
	``BOM_TOO_LARGE``, ``SET_TYPE_CODE_EXISTS``, ``BOM_LINE_INVALID`` (``items`` = lỗi từng dòng). Lỗi phần đầu (thiếu
	trường bắt buộc, loại gói/hạn lưu, GTIN…) là ``frappe.ValidationError`` của ``InstrumentSetType.validate``.
	"""
	header = dict(header or {})
	type_code = header.get("type_code")
	type_code = type_code.strip().upper() if isinstance(type_code, str) else type_code
	rows = _rows_or_block(lines)
	if type_code and frappe.db.exists(SET_TYPE, type_code):
		raise BlockedError(code_exists_block(type_code))
	errors = line_errors(header.get("method"), rows, lock=True)
	if errors:
		raise BlockedError(_lines_block(errors))
	values = {field: header[field] for field in HEADER_FIELDS if field in header}
	doc = frappe.get_doc({"doctype": SET_TYPE, **values, "type_code": type_code, "current_bom_version": 1})
	doc.flags.tc_bom = True
	frappe.db.savepoint(SAVEPOINT)
	try:
		doc.insert()
		_insert_lines(doc.name, 1, rows, today(), reason or _("Initial version"), 0)
	except frappe.DuplicateEntryError:
		# request song song vừa tạo cùng mã
		frappe.db.rollback(save_point=SAVEPOINT)
		raise BlockedError(code_exists_block(type_code)) from None
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return doc.name


def _parse_date(value) -> date | None:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	if isinstance(value, str) and _ISO_DATE.fullmatch(value.strip()):
		try:
			return date.fromisoformat(value.strip())
		except ValueError:
			return None
	return None


def _lock_set_type(set_type) -> dict:
	row = None
	if isinstance(set_type, str) and set_type:
		rows = frappe.db.sql(
			"select name, method, current_bom_version from `tabInstrument Set Type` where name = %s for update",
			(set_type,),
			as_dict=True,
		)
		row = rows[0] if rows else None
	if not row:
		raise BlockedError(not_found_block(set_type))
	return row


def _latest(set_type: str) -> tuple[int, date | None]:
	"""Phiên bản mới nhất và ngày hiệu lực của nó, đọc có khóa (thấy cả phiên bản vừa commit sau snapshot)."""
	rows = frappe.db.sql(
		"""
		select bom_version, effective_from from `tabSet BOM Item`
		where set_type = %s
		order by bom_version desc
		limit 1
		for update
		""",
		(set_type,),
	)
	if not rows:
		return 0, None
	return cint(rows[0][0]), getdate(rows[0][1]) if rows[0][1] else None


def create_version(set_type: str, lines: list[dict], effective_from, reason: str, base_version: int) -> dict:
	"""Lưu phiên bản BOM mới (copy-on-edit từ `base_version`) của loại bộ (FR-M1-04, .4; S2, S4, S5, S14).

	Trả ``{set_type, bom_version, effective_from (ISO), status}``. Từ chối (``BlockedError``, không ghi gì):
	``REASON_REQUIRED`` (trống/chỉ khoảng trắng/quá 500 ký tự), ``BOM_EFFECTIVE_DATE_INVALID`` (sai định dạng, trước
	hôm nay, trước ngày của phiên bản mới nhất), ``BOM_EMPTY``, ``BOM_TOO_LARGE``, ``SET_TYPE_NOT_FOUND``,
	``BOM_VERSION_CONFLICT`` (``items = [{latest}]``), ``BOM_LINE_INVALID`` (không có thay đổi, hoặc lỗi từng dòng).
	Loại bộ cũ chưa có dòng BOM nào nhận phiên bản đầu tiên với ``base_version = 0``. Hiệu lực hôm nay →
	``current_bom_version`` đổi ngay (ghi thẳng, không lưu lại phần đầu: loại bộ cũ thiếu khoa/loại gói vẫn nhận).
	Một Audit Log ``Update`` trên loại bộ (lý do = `reason`) + Comment trên timeline (trừ phiên bản đầu tiên); mỗi dòng
	có Audit ``Create``.
	"""
	reason = reason.strip() if isinstance(reason, str) else ""
	if not reason:
		raise BlockedError(_reason_block(_("A reason is required to save a new BOM version.")))
	if len(reason) > REASON_MAX:
		raise BlockedError(
			_reason_block(
				_("The reason has {0} characters; at most {1} are allowed.").format(len(reason), REASON_MAX)
			)
		)
	day = _parse_date(effective_from)
	if day is None:
		raise BlockedError(
			_date_block(_("Effective date {0} is not a valid date.").format(cstr(effective_from)[:40] or "-"))
		)
	if day < today():
		raise BlockedError(_date_block(_("Effective date {0} is in the past.").format(formatdate(day))))
	base = whole_number(base_version)
	if base is None or base < 0:
		frappe.throw(_("Base version must be a whole number of at least 0."))
	rows = _rows_or_block(lines)

	header = _lock_set_type(set_type)
	set_type = header.name
	latest, latest_day = _latest(set_type)
	if base != latest:
		raise BlockedError(
			Block(
				"BOM_VERSION_CONFLICT",
				_("BOM changed meanwhile"),
				_("You edited BOM version {0}, but the latest version is now {1}.").format(base, latest),
				_("Reload the BOM and make your change again."),
				items=[{"latest": latest}],
			)
		)
	if latest_day and day < latest_day:
		raise BlockedError(
			_date_block(
				_("Effective date {0} is earlier than BOM version {1}, effective from {2}.").format(
					formatdate(day), latest, formatdate(latest_day)
				)
			)
		)
	if latest and [(row["instrument"], row["qty"]) for row in rows] == _version_lines(
		set_type, latest, lock=True
	):
		raise BlockedError(
			Block(
				"BOM_LINE_INVALID",
				_("No changes"),
				_("The BOM is the same as version {0}.").format(latest),
				_("Change at least one line, or close without saving."),
			)
		)
	errors = line_errors(header.method, rows, lock=True)
	if errors:
		raise BlockedError(_lines_block(errors))

	new = latest + 1
	values = {
		"bom_version": new,
		"effective_from": str(day),
		"based_on_version": base,
		"line_count": len(rows),
		"total_qty": sum(row["qty"] for row in rows),
	}
	old, status = None, STATUS_SCHEDULED
	frappe.db.savepoint(SAVEPOINT)
	try:
		_insert_lines(set_type, new, rows, day, reason, base)
		if day == today():
			status = STATUS_EFFECTIVE
			current = cint(header.current_bom_version)
			if current != new:
				frappe.db.set_value(SET_TYPE, set_type, "current_bom_version", new)
				old = {"current_bom_version": current}
				values["current_bom_version"] = new
		audit.log("Update", SET_TYPE, set_type, old=old, new=values, reason=reason)
		if latest:
			# phiên bản thay cho phiên bản khác: ghi timeline (phiên bản đầu đi cùng việc tạo loại bộ / BOM đầu tiên)
			_comment(set_type, new, day, base, reason)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return {"set_type": set_type, "bom_version": new, "effective_from": str(day), "status": status}


def _comment(set_type: str, version: int, day: date, base: int, reason: str):
	content = _(
		"BOM version {0} saved by {1} (based on version {2}), effective from {3}. Reason: {4}"
	).format(version, frappe.session.user, base, formatdate(day), reason)
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": SET_TYPE,
			"reference_name": set_type,
			"content": escape_html(content),
		}
	).insert(ignore_permissions=True)


def copy_set_type(source: str, type_code: str, set_type_name: str) -> str:
	"""Sao chép loại bộ (UC-02 A2, S13): phần đầu trừ mã/tên/GTIN/ảnh + dòng của phiên bản hiệu lực thành v1 mới.

	Nguồn không có → ``SET_TYPE_NOT_FOUND``; mã trùng → ``SET_TYPE_CODE_EXISTS``; dòng có dụng cụ đã Ngừng sử dụng /
	không tương thích → ``BOM_LINE_INVALID`` như khi tạo (S5). Trả mã loại bộ mới.
	"""
	source_row = (
		frappe.db.get_value(SET_TYPE, source, ["name", *COPY_FIELDS], as_dict=True)
		if isinstance(source, str) and source
		else None
	)
	if not source_row:
		raise BlockedError(not_found_block(source))
	version = effective_version(source_row.name)
	lines = (
		[{"instrument": code, "qty": qty} for code, qty in _version_lines(source_row.name, version)]
		if version
		else []
	)
	header = {field: source_row[field] for field in COPY_FIELDS}
	header.update({"type_code": type_code, "set_type_name": set_type_name})
	return create_set_type(
		header, lines, reason=_("Copied from set type {0}, BOM version {1}").format(source_row.name, version)
	)


def roll_effective_versions() -> list[str]:
	"""Scheduler cron ``0 0 * * *`` (giờ hệ thống): đưa ``current_bom_version`` về phiên bản áp dụng hôm nay.

	Loại bộ có giá trị khác ``effective_version`` → ghi thẳng + Audit Log ``Update`` (reason ``scheduled``). Chạy lại
	không đổi gì; trả danh sách loại bộ đã đổi. Mỗi loại bộ khóa dòng rồi tính lại (không đè phiên bản vừa lưu).
	"""
	day = today()
	candidates = frappe.db.sql(
		"""
		select st.name
		from `tabInstrument Set Type` st
		join (
			select set_type, max(bom_version) as version from `tabSet BOM Item`
			where effective_from is null or effective_from <= %s
			group by set_type
		) eff on eff.set_type = st.name
		where ifnull(st.current_bom_version, 0) != eff.version
		order by st.name
		""",
		(day,),
		pluck=True,
	)
	changed = []
	for name in candidates:
		current = cint(_lock_set_type(name).current_bom_version)
		effective = _max_effective(name, day, lock=True)
		if not effective or effective == current:
			continue
		frappe.db.set_value(SET_TYPE, name, "current_bom_version", effective)
		audit.log(
			"Update",
			SET_TYPE,
			name,
			old={"current_bom_version": current},
			new={"current_bom_version": effective},
			reason=SCHEDULED_REASON,
		)
		changed.append(name)
	return changed


# --- Phiên bản của một bộ (S3) ---------------------------------------------------------------------------------


def pin_cycle_version(ctx: dict) -> int | None:
	"""Hook ``tracecore_cycle_bom_version`` (``core.step_gate.start_cycle``): phiên bản ghim cho chu trình mới.

	``ctx = {"set_unit", "set_type", "cycle_no", "on"}``; trả phiên bản hiệu lực tại ngày tiếp nhận ``on``
	(FR-M1-04.2: từ ngày hiệu lực trở đi chu trình mới dùng phiên bản mới), None khi loại bộ chưa có phiên bản hiệu lực.
	Chỉ đọc; step_gate ghi ``Set Unit.cycle_bom_version``.
	"""
	return effective_version(ctx["set_type"], ctx.get("on"))


def version_for_set_unit(set_unit) -> int | None:
	"""Phiên bản BOM áp dụng cho bộ `set_unit` (tên hoặc dict có ``name``), FR-M1-04.1.

	Đã ghim (``cycle_bom_version > 0``, bộ đang trong chu trình) → phiên bản ghim. Chưa ghim (bộ cũ chưa có chu trình
	từ FEAT-015) → phiên bản hiệu lực hôm nay; loại bộ chưa có phiên bản hiệu lực → ``current_bom_version`` của loại
	bộ như FEAT-018 (cùng quy tắc ``set_type.live_versions``). Bộ không có → None.
	"""
	name = set_unit.get("name") if isinstance(set_unit, dict) else set_unit
	row = frappe.db.get_value("Set Unit", name, ["set_type", "cycle_bom_version"]) if name else None
	if not row:
		return None
	set_type, pinned = row
	if cint(pinned) > 0:
		return cint(pinned)
	return (
		effective_version(set_type)
		or cint(frappe.db.get_value(SET_TYPE, set_type, "current_bom_version"))
		or None
	)
