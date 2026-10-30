"""Dải Cycle ID cấp trước cho trạm dùng khi mất mạng (ADR-003, FR-M9-06.2, FR-M2-07.11; A-40 Q4).

Mỗi dải 200 số liên tiếp của series ``CY-YYMMDD-T<NNN>-`` (NNN = số của trạm ``TR-NNN``), cấp khi trạm online và hết
hiệu lực 00:00 ngày sau. Số lấy từ ``tabSeries`` theo khối (khóa dòng tới commit) nên hai dải không bao giờ chồng
nhau. Khi phát lại, `claim` chỉ nhận mã thuộc dải của đúng trạm, đúng ngày nghiệp vụ, chưa có trong Code Registry.
"""

import re
from datetime import date, datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime

from tracecore.core import code_registry
from tracecore.core.errors import Block, BlockedError

SIZE = 200
REFILL_RATIO = 0.2
MAX_NO = 9999
_STATION = re.compile(r"TR-(\d{3})")
_OFFLINE_CODE = re.compile(r"(CY-\d{6}-T\d{3}-)(\d{4})")
FIELDS = ["name", "prefix", "from_no", "to_no", "expires_at"]


def prefix_for(station: str, on: date) -> str:
	match = _STATION.fullmatch(station or "")
	if not match:
		frappe.throw(_("Station {0} has no TR-NNN code for offline Cycle IDs.").format(station))
	return f"{code_registry.CYCLE_PREFIX}-{getdate(on):%y%m%d}-T{match.group(1)}-"


def _invalid(code):
	return BlockedError(
		Block(
			"CODE_RANGE_INVALID",
			_("Offline Cycle ID is not valid"),
			_("Code {0} is not in an unused offline range of this station for that day.").format(code),
			_("Keep the pack aside and report it to R02."),
		)
	)


def _reserve(key: str, size: int) -> tuple[int, int]:
	"""Giữ `size` số kế tiếp của series `key` (đọc có khóa dòng ``tabSeries``)."""
	row = frappe.db.sql("select `current` from `tabSeries` where name = %s for update", key)
	if row:
		start = cint(row[0][0])
	else:
		start = 0
		frappe.db.sql("insert into `tabSeries` (`name`, `current`) values (%s, 0)", key)
	if start + size > MAX_NO:
		raise BlockedError(
			Block(
				"CODE_RANGE_EXHAUSTED",
				_("No offline codes left today"),
				_("This station has used every offline Cycle ID number for today."),
				_("Pack while online, or call R10."),
			)
		)
	frappe.db.sql("update `tabSeries` set `current` = %s where name = %s", (start + size, key))
	return start + 1, start + size


def allocate(station: str, on: date, session: str | None = None) -> dict:
	"""Cấp một dải 200 mã mới cho `station` ngày `on`; trả ``{name, prefix, from_no, to_no, expires_at}``."""
	on = getdate(on)
	prefix = prefix_for(station, on)
	from_no, to_no = _reserve(prefix, SIZE)
	doc = frappe.get_doc(
		{
			"doctype": "Code Range",
			"station": station,
			"prefix": prefix,
			"range_date": on,
			"from_no": from_no,
			"to_no": to_no,
			"issued_at": now_datetime(),
			"issued_to": session,
			"expires_at": datetime.combine(on + timedelta(days=1), time()),
		}
	).insert(ignore_permissions=True)
	return {field: doc.get(field) for field in FIELDS}


def _ranges(station, on):
	return frappe.get_all(
		"Code Range",
		filters={"station": station, "range_date": getdate(on)},
		fields=FIELDS,
		order_by="from_no asc",
	)


def _used_numbers(prefix):
	codes = frappe.get_all("Code Registry", filters={"code": ("like", prefix + "%")}, pluck="code")
	return sorted(int(code[len(prefix) :]) for code in codes if code[len(prefix) :].isdigit())


def ensure(station: str, on: date, session: str | None = None) -> list[dict]:
	"""Mọi dải của trạm trong ngày, mỗi dải kèm ``used`` (số đã ghi sổ trên server, để kiosk mất dữ liệu cục bộ không
	cấp lại); chưa có dải, hoặc số chưa dùng < 20 % một dải thì cấp thêm một dải."""
	ranges = _ranges(station, on)
	used = _used_numbers(ranges[0].prefix) if ranges else []
	if not ranges or sum(row.to_no - row.from_no + 1 for row in ranges) - len(used) < SIZE * REFILL_RATIO:
		allocate(station, on, session)
		ranges = _ranges(station, on)
	return [{**row, "used": [no for no in used if row.from_no <= no <= row.to_no]} for row in ranges]


def claim(code: str, station: str, on: date) -> None:
	"""Nhận mã offline `code` cho gói đóng ngày `on` tại `station` và ghi sổ; sai → ``CODE_RANGE_INVALID``."""
	match = _OFFLINE_CODE.fullmatch(code or "")
	if not match or match.group(1) != prefix_for(station, on):
		raise _invalid(code)
	number = int(match.group(2))
	inside = frappe.db.exists(
		"Code Range",
		{
			"station": station,
			"range_date": getdate(on),
			"from_no": ("<=", number),
			"to_no": (">=", number),
		},
	)
	if not inside:
		raise _invalid(code)
	try:
		code_registry.register(code, code_registry.CYCLE_PREFIX, "Pack", code, station)
	except code_registry.CodeAlreadyIssuedError:
		raise _invalid(code) from None
