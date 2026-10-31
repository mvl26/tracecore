"""Cấp mã đối tượng và ghi sổ Code Registry (FR-M9-07, BRU-ID-001, BRU-ID-006)."""

import re

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import now_datetime

from tracecore.core import gs1
from tracecore.core.errors import Block, BlockedError

SET_SERIAL_DIGITS = gs1.SET_SERIAL_DIGITS
SET_SERIES_MAX = (
	10**SET_SERIAL_DIGITS - 1
)  # 999 999: số tiếp theo → lỗi "series đã hết", không cấp mã 7 số (G2)
INSTRUMENT_GIAI_PREFIX = (
	"GI"  # mã GIAI khắc laser của dụng cụ `<prefix>I-########`, ref_doctype = Instrument (A-06 I8)
)
ROLL_PREFIX = "CN"  # cuộn nhãn `CN-#####` do FEAT-005 cấp, ref_doctype = Item nhãn (D2)
CYCLE_PREFIX = "CY"  # Cycle ID `CY-YYMMDD-NNNN` của gói, ref_doctype = Pack (§5.3.3)
CYCLE_SERIAL_DIGITS = 4
GTIN_SERIES = "GTIN"  # bộ đếm `GTIN<prefix>` và dòng sổ của GTIN-14 tự cấp (A-76)
GTIN_LOW_PERCENT = 10  # cảnh báo R10 khi số mã tham chiếu còn lại dưới 10 % dải
CONTAINER_PREFIX = (
	"CT"  # túi/thùng chất thải `CT-YYMMDD-NNNNN`, ref_doctype = Waste Container (§5.3.3, FEAT-047)
)
CONTAINER_SERIAL_DIGITS = 5
# Mã đối tượng QR nội bộ (§5.3.3): prefix sổ → (khóa series, số chữ số). Khóa series trùng naming series
# của DocType (vd Equipment `TB-.####`) nên hai đường cấp dùng chung một bộ đếm.
CODE_FORMATS = {"NV": ("NV-", 5), "TB": ("TB-", 4), "KE": ("KE-", 4), "TR": ("TR-", 3), "CN": ("CN-", 5)}
CARD_PREFIX = "CARD"  # thẻ có sẵn của bệnh viện đăng ký làm mã thẻ (FR-M9-07.4)
CARD_MIN_LENGTH = 4
CARD_MAX_LENGTH = 40
# Tiền tố mã hệ thống: thẻ bệnh viện không được bắt đầu bằng các tiền tố này (dễ lẫn với mã do hệ thống sinh)
SYSTEM_CODE_PREFIXES = ("NV-", "TB-", "KE-", "TR-", "CN-", "CT-", "CY-", "LR-", "ME-")


SET_TYPE_CODE = re.compile(r"[A-Z0-9]{2,8}")  # mã loại bộ nằm trong Set ID (§5.3.3, A-02)


class CodeAlreadyIssuedError(frappe.ValidationError):
	pass


class SeriesExhaustedError(frappe.ValidationError):
	"""Bộ đếm series đã hết dải số theo độ rộng: không cấp mã dài hơn (nơi gọi đổi thành Block nếu cần)."""


class InvalidCardCodeError(frappe.ValidationError):
	pass


def company_prefix():
	return gs1.configured_company_prefix()


def is_issued(code):
	return bool(frappe.db.exists("Code Registry", code))


def roll_label_item(roll_code):
	"""Item nhãn của cuộn `CN-#####`, hoặc None.

	Chỉ nhận dòng sổ có prefix ``CN``, ``ref_doctype = Item`` và còn Active; Item đó có phải nhãn hay không
	do nơi gọi kiểm (`core.print.set_roll`).
	"""
	if not roll_code:
		return None
	row = frappe.db.get_value(
		"Code Registry", roll_code, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
	)
	if row and (row.prefix, row.ref_doctype, row.status) == (ROLL_PREFIX, "Item", "Active"):
		return row.ref_name or None
	return None


def register(code, prefix, ref_doctype=None, ref_name=None, station=None):
	"""Ghi một mã vào sổ; mã đã có (kể cả đã vô hiệu) → CodeAlreadyIssuedError."""
	if is_issued(code):
		raise CodeAlreadyIssuedError(_("Code {0} has already been issued.").format(code))
	doc = frappe.get_doc(
		{
			"doctype": "Code Registry",
			"code": code,
			"prefix": prefix,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"issued_at": station,
			"issued_on": now_datetime(),
			"status": "Active",
		}
	)
	# ref_name có thể là bản ghi đang được tạo trong cùng transaction (Set Unit)
	doc.flags.ignore_links = True
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		raise CodeAlreadyIssuedError(_("Code {0} has already been issued.").format(code))
	return doc.name


def disable(code, reason):
	"""Vô hiệu một mã đã cấp (vd Cycle ID của gói bị hủy); mã vẫn nằm trong sổ nên không bao giờ cấp lại."""
	if not is_issued(code):
		frappe.throw(_("Code {0} has not been issued.").format(code), frappe.DoesNotExistError)
	doc = frappe.get_doc("Code Registry", code, for_update=True)
	doc.update({"status": "Disabled", "disabled_reason": reason, "disabled_on": now_datetime()})
	doc.save(ignore_permissions=True)


def next_code(prefix, ref_doctype=None, ref_name=None, station=None):
	"""Cấp mã đối tượng `NV-#####`, `TB-####`, `KE-####`, `TR-###`, `CN-#####` và ghi sổ trong cùng transaction.

	Bộ đếm qua `getseries` (khóa dòng ``tabSeries`` FOR UPDATE nên hai request đồng thời không ra trùng);
	số đã có trong sổ (đăng ký tay, patch) thì bỏ qua. Hết dải số theo độ rộng → lỗi, không cấp mã dài hơn.
	"""
	if prefix not in CODE_FORMATS:
		frappe.throw(_("Unknown code prefix: {0}.").format(prefix), frappe.ValidationError)
	series_key, digits = CODE_FORMATS[prefix]
	while True:
		serial = getseries(series_key, digits)
		if len(serial) > digits:
			frappe.throw(
				_("Code series {0} is exhausted.").format(series_key + "#" * digits), frappe.ValidationError
			)
		code = series_key + serial
		if not is_issued(code):
			register(code, prefix, ref_doctype, ref_name, station)
			return code


def register_card(code, ref_doctype, ref_name):
	"""Đăng ký thẻ có sẵn của bệnh viện làm mã thẻ (FR-M9-07.4), prefix sổ ``CARD``; trả mã đã làm sạch.

	Chỉ nhận mã quét được: sau `gs1.clean_scan` dài 4-40 ký tự GS1 CSET 82, không bắt đầu bằng tiền tố
	mã hệ thống, không phải Set ID GIAI hay mã khác mà `parse_scan` nhận ra, và chưa có trong sổ.
	"""
	if not ref_doctype or not ref_name:
		frappe.throw(_("A hospital card must be registered to a record."), InvalidCardCodeError)
	value = gs1.clean_scan(code)
	if not CARD_MIN_LENGTH <= len(value) <= CARD_MAX_LENGTH or not set(value) <= gs1.CSET82:
		frappe.throw(
			_("Card code {0} must be {1}-{2} characters without spaces or accented letters.").format(
				value, CARD_MIN_LENGTH, CARD_MAX_LENGTH
			),
			InvalidCardCodeError,
		)
	if value.upper().startswith(SYSTEM_CODE_PREFIXES) or gs1.parse_scan(value)["type"] != "unknown":
		frappe.throw(
			_("Card code {0} looks like a system-generated code and cannot be registered.").format(value),
			InvalidCardCodeError,
		)
	return register(value, CARD_PREFIX, ref_doctype, ref_name)


def next_cycle_id(packed_at, station=None):
	"""Cấp Cycle ID `CY-YYMMDD-NNNN` và ghi sổ (prefix ``CY``, ref Pack = chính mã đó).

	Series đếm theo ngày của `packed_at` (giờ hệ thống, D13): khóa ``CY-YYMMDD-``; số đã có trong sổ thì bỏ qua.
	"""
	series_key = f"{CYCLE_PREFIX}-{packed_at:%y%m%d}-"
	while True:
		code = series_key + getseries(series_key, CYCLE_SERIAL_DIGITS)
		if not is_issued(code):
			register(code, CYCLE_PREFIX, "Pack", code, station)
			return code


def next_set_id(type_code):
	"""Cấp Set ID GIAI mới = tiền tố GS1 + mã loại bộ + số thứ tự 6 chữ số, và ghi sổ (FEAT-016 G2, G3).

	Series riêng theo (tiền tố, mã loại bộ) qua `getseries` (khóa dòng ``tabSeries`` tới commit); số đã có trong sổ
	(đăng ký tay, đã vô hiệu) thì bỏ qua nên không bao giờ cấp lại (BRU-ID-001). Tiền tố demo ngoài site dev/test hoặc
	sai định dạng → `BlockedError` ``GS1_PREFIX_NOT_CONFIGURED`` trước `getseries`; quá ``SET_SERIES_MAX`` →
	`SeriesExhaustedError` (``ValidationError``) "series đã hết", không cấp mã 7 số. `type_code` không đúng
	``[A-Z0-9]{2,8}`` → ``ValidationError`` trước mọi ghi (phòng thủ cho nơi gọi trực tiếp).
	"""
	if not isinstance(type_code, str) or not SET_TYPE_CODE.fullmatch(type_code):
		frappe.throw(
			_("Set type code {0} is not valid for a Set ID.").format(repr(type_code)), frappe.ValidationError
		)
	prefix = company_prefix()
	block = gs1_prefix_block(prefix, "set")
	if block:
		raise BlockedError(block)
	series_key = f"{prefix}{type_code}"
	while True:
		serial = getseries(series_key, SET_SERIAL_DIGITS)
		if len(serial) > SET_SERIAL_DIGITS:
			frappe.throw(
				_("Code series {0} is exhausted.").format(series_key + "#" * SET_SERIAL_DIGITS),
				SeriesExhaustedError,
			)
		code = gs1.make_giai(prefix, f"{type_code}{serial}")
		if not is_issued(code):
			register(code, series_key, "Set Unit", code)
			return code


def gtin_series_key(prefix):
	"""Bộ đếm mã tham chiếu theo từng mã doanh nghiệp: đổi prefix rồi quay lại vẫn không cấp trùng (A-76)."""
	return f"{GTIN_SERIES}{prefix}"


def gtin_range(lock=False):
	"""Dải mã tham chiếu của prefix đã khai, hoặc ``None`` khi chưa khai. `lock` giữ dòng bộ đếm tới hết transaction.

	Bộ đếm nằm ở ``tabSeries``, không ở Singles: lưu form Settings ghi lại cả Single nên sẽ đè số mới bằng số cũ.
	"""
	prefix = gs1.declared_company_prefix()
	if not gs1.is_valid_gtin_prefix(prefix):
		return None
	if lock:
		_ensure_gtin_series(prefix)
	suffix = " FOR UPDATE" if lock else ""
	found = frappe.db.sql(f"SELECT current FROM `tabSeries` WHERE name=%s{suffix}", gtin_series_key(prefix))  # nosec B608
	current = found[0][0] if found and found[0][0] else 0
	capacity = gs1.gtin_ref_capacity(prefix)
	remaining = max(capacity - current, 0)
	return {
		"prefix": prefix,
		"indicator": gs1.gtin_indicator_digit(),
		"next_ref": current + 1,
		"capacity": capacity,
		"remaining": remaining,
		"low": _gtin_low(remaining, capacity),
	}


def _ensure_gtin_series(prefix):
	# dòng phải có trước khi khóa: FOR UPDATE trên dòng chưa có là gap lock, hai người cùng cấp mã đầu tiên sẽ deadlock
	frappe.db.sql("INSERT IGNORE INTO `tabSeries` (name, current) VALUES (%s, 0)", gtin_series_key(prefix))


def _gtin_low(remaining, capacity):
	return remaining * 100 < capacity * GTIN_LOW_PERCENT


def _gtin_taken(gtin, doctype):
	return is_issued(gtin) or bool(frappe.db.exists(doctype, {"gtin": gtin}))


def next_gtin(ref_doctype, ref_name):
	"""Cấp GTIN-14 kế tiếp và ghi sổ; chưa khai prefix → ``None``, giữ hành vi nhập tay (A-76).

	`getseries` khóa dòng ``tabSeries`` tới commit nên hai người tạo cùng lúc không ra trùng. Mã đã có trong sổ hoặc đã
	nằm trên bản ghi (nhập tay) thì bỏ qua. Hết dải → `SeriesExhaustedError`. Vừa xuống dưới 10 % dải thì báo R10 một lần.
	"""
	state = gtin_range()
	if not state:
		return None
	prefix, capacity = state["prefix"], state["capacity"]
	key = gtin_series_key(prefix)
	_ensure_gtin_series(prefix)
	while True:
		item_ref = int(getseries(key, len(str(capacity))))
		if item_ref > capacity:
			frappe.throw(
				_(
					"GS1 item references of prefix {0} are used up. Enter the GTIN-14 by hand or ask R10 for another prefix."
				).format(prefix),
				SeriesExhaustedError,
			)
		gtin = gs1.make_gtin14(state["indicator"], prefix, item_ref)
		if _gtin_taken(gtin, ref_doctype):
			continue
		register(gtin, key, ref_doctype, ref_name)
		remaining = capacity - item_ref
		if _gtin_low(remaining, capacity) and not state["low"]:
			_notify_gtin_low(prefix, remaining, capacity)
		return gtin


def peek_gtins(ref_doctype, count):
	"""`count` mã sẽ được cấp tiếp, không ghi gì, cho màn xem trước. Chưa khai prefix hoặc không đủ dải → `BlockedError`."""
	state = gtin_range()
	if not state:
		raise BlockedError(prefix_not_declared_block())
	result = []
	item_ref = state["next_ref"]
	while len(result) < count:
		if item_ref > state["capacity"]:
			raise BlockedError(
				Block(
					"GTIN_RANGE_EXHAUSTED",
					_("GTIN-14 not issued"),
					_("Only {0} item references are left for prefix {1}, {2} are needed.").format(
						len(result), state["prefix"], count
					),
					_("Enter the remaining GTIN-14 by hand."),
				)
			)
		gtin = gs1.make_gtin14(state["indicator"], state["prefix"], item_ref)
		if not _gtin_taken(gtin, ref_doctype):
			result.append(gtin)
		item_ref += 1
	return result


def retire_gtin(gtin, ref_doctype, ref_name):
	"""GTIN đã in lên nhãn rồi bị thay: ghi vào sổ để bộ đếm không bao giờ cấp lại."""
	if gtin and not is_issued(gtin):
		register(gtin, GTIN_SERIES, ref_doctype, ref_name)


def prefix_not_declared_block():
	return Block(
		"GS1_PREFIX_NOT_DECLARED",
		_("GS1 company prefix not declared"),
		_("GTIN-14 cannot be issued without the hospital's GS1 company prefix."),
		_("Enter it in the GS1 section of TraceCore Settings, save, then try again."),
	)


def prefix_in_use(prefix):
	"""Prefix thật đã có GTIN hoặc mã GIAI được cấp: không đổi nữa. Prefix demo luôn thay được bằng prefix thật."""
	if not prefix or gs1.is_demo_prefix(prefix):
		return False
	if frappe.db.get_value("Series", gtin_series_key(prefix), "current", order_by=None):
		return True
	return bool(frappe.db.exists("Code Registry", {"code": ("like", f"{prefix}%")}))


def _notify_gtin_low(prefix, remaining, capacity):
	from tracecore.core import notification

	notification.emit(
		"GTIN_RANGE_LOW",
		subject=_("GS1 item references are running low"),
		message=_("Prefix {0} has {1} of {2} item references left.").format(prefix, remaining, capacity),
		link="/app/tracecore-settings",
	)


def demo_prefix_allowed():
	"""Tiền tố demo chỉ dùng trên site dev/test (developer_mode, allow_tests hoặc đang chạy test), như devdata."""
	return bool(frappe.conf.get("developer_mode") or frappe.conf.get("allow_tests") or frappe.flags.in_test)


GS1_PREFIX_PURPOSES = ("instrument", "set")


def _prefix_block_texts(purpose):
	"""(lý do, hành động) của Block tiền tố GS1 theo mục đích; chuỗi viết nguyên văn để `_()` trích được."""
	if purpose == "instrument":
		return (
			_(
				"GS1 Company Prefix {0} cannot be used for instrument codes on this site: it is the demo prefix or is not 4-12 digits."
			),
			_(
				"Ask the administrator to set the hospital's real GS1 Company Prefix before assigning or etching instrument codes."
			),
		)
	return (
		_(
			"GS1 Company Prefix {0} cannot be used for Set IDs on this site: it is the demo prefix or is not 4-12 digits."
		),
		_(
			"Ask the administrator to set the hospital's real GS1 Company Prefix before issuing or printing Set ID tags."
		),
	)


def gs1_prefix_block(prefix, purpose="instrument"):
	"""Block ``GS1_PREFIX_NOT_CONFIGURED`` nếu tiền tố GS1 chưa dùng được cho mã không sửa được; dùng được → ``None``.

	Mã khắc laser dụng cụ (``purpose = "instrument"``, A-06 I8) và thẻ Set ID (``"set"``, FEAT-016 G3) không xóa
	được (OQ-05/D6): tiền tố phải là 4-12 chữ số ASCII; tiền tố thuộc dải demo ``952`` chỉ dùng trên site dev/test.
	"""
	if purpose not in GS1_PREFIX_PURPOSES:
		raise ValueError(f"Unknown GS1 prefix purpose: {purpose!r}")
	prefix = str(prefix or "")
	valid = prefix.isascii() and prefix.isdecimal() and 4 <= len(prefix) <= 12
	if valid and (not gs1.is_demo_prefix(prefix) or demo_prefix_allowed()):
		return None
	reason, action = _prefix_block_texts(purpose)
	return Block(
		"GS1_PREFIX_NOT_CONFIGURED", _("GS1 prefix not configured"), reason.format(prefix or "-"), action
	)


def etching_prefix_block(prefix):
	"""Bí danh `gs1_prefix_block(prefix, "instrument")` (FEAT-014: mã khắc laser dụng cụ)."""
	return gs1_prefix_block(prefix, "instrument")


def set_id_block(set_id, type_code):
	"""`gs1_prefix_block(…, "set")` theo tiền tố **chứa trong** Set ID đã cấp (FEAT-016 G3).

	Set ID cấp trên dev/test (tiền tố demo) rồi DB bị chép sang site thật thì không được in/in lại/xuất CSV, dù tiền tố
	cấu hình hiện tại là thật. Mã không đúng cấu trúc Set ID của `type_code` (`gs1.split_set_id`) → không xác định
	được tiền tố → cũng chặn.
	"""
	try:
		prefix, _serial = gs1.split_set_id(set_id, type_code)
	except gs1.GS1Error:
		prefix = None
	return gs1_prefix_block(prefix, "set")


def instrument_giai_block(giai):
	"""``etching_prefix_block`` theo tiền tố **chứa trong** mã GIAI dụng cụ đã cấp (``<prefix>I-########``).

	Mã cấp trên dev/test (tiền tố demo) rồi DB được chép sang site thật thì không được xem trước để khắc hay ghi nhận
	đã khắc, dù tiền tố cấu hình hiện tại là thật.
	"""
	suffix = len(gs1.INSTRUMENT_ASSET_PREFIX) + gs1.INSTRUMENT_SERIAL_DIGITS
	return etching_prefix_block(str(giai or "")[:-suffix])


def next_instrument_giai(instrument):
	"""Cấp mã GIAI khắc laser cho dụng cụ `instrument` (`<prefix>I-########`) và ghi sổ (prefix ``GI``, A-06 I8).

	Series riêng (khóa ``<prefix>I-``, khóa dòng ``tabSeries`` nên hai request đồng thời không ra trùng); số đã có
	trong sổ (kể cả mã đã vô hiệu) thì bỏ qua, nên mã không bao giờ cấp lại (BRU-ID-001). Tiền tố demo ngoài site
	dev/test hoặc tiền tố sai định dạng → `BlockedError` ``GS1_PREFIX_NOT_CONFIGURED`` trước mọi ghi.
	"""
	prefix = company_prefix()
	block = etching_prefix_block(prefix)
	if block:
		raise BlockedError(block)
	series_key = f"{prefix}{gs1.INSTRUMENT_ASSET_PREFIX}"
	digits = gs1.INSTRUMENT_SERIAL_DIGITS
	while True:
		serial = getseries(series_key, digits)
		if len(serial) > digits:
			frappe.throw(
				_("Code series {0} is exhausted.").format(series_key + "#" * digits), frappe.ValidationError
			)
		code = gs1.make_instrument_giai(prefix, int(serial))
		if not is_issued(code):
			register(code, INSTRUMENT_GIAI_PREFIX, "Instrument", instrument)
			return code


def next_container_code(collected_at, station=None):
	"""Cấp mã túi/thùng chất thải `CT-YYMMDD-NNNNN` và ghi sổ (FR-M10-01.5, BRU-ID-006); số đã có trong sổ thì bỏ qua."""
	series_key = f"{CONTAINER_PREFIX}-{collected_at:%y%m%d}-"
	while True:
		code = series_key + getseries(series_key, CONTAINER_SERIAL_DIGITS)
		if not is_issued(code):
			register(code, CONTAINER_PREFIX, "Waste Container", code, station)
			return code
