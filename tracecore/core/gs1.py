"""Sinh và phân tích mã GS1 cho TraceCore (ADR-004).

Nơi duy nhất tạo Set ID GIAI và mã GIAI dụng cụ (AI 8004) và payload Cycle ID (AI 01, 11, 17, 21),
mã phiên bản BOM trên phiếu kiểm đếm (``BOM-<mã loại bộ>-V<n>``, không phải GS1), kiểm GTIN-14, phân tích chuỗi quét
từ máy quét HID
và mã hóa DataMatrix (ảnh PNG qua libdmtx, lệnh ZPL ``^BXN`` cho máy in).
Hàm ở đây thuần Python, không đọc/ghi DB.
"""

import ctypes
import io
import re
import string
from ctypes import byref, cast
from datetime import date, datetime

GS = "\x1d"  # FNC1 trong chuỗi dữ liệu (GS1 dùng GS làm FNC1 / phân cách AI)
AI_GIAI = "8004"
AI_GTIN = "01"
AI_PACKED = "11"
AI_EXPIRY = "17"
AI_SERIAL = "21"
DEFAULT_COMPANY_PREFIX = "9520000"  # prefix GS1 "952" dành cho demo — chỉ dev/staging (OQ-05)
TEST_GTIN_PREFIX = "0952"  # chỉ thị 0 + prefix demo 952: GTIN-14 do make_test_gtin14 sinh
MAX_GIAI_LENGTH = 30
MAX_SERIAL_LENGTH = 20  # độ dài tối đa của AI (21)
MAX_SCAN_LENGTH = 120
DEMO_PREFIX_RANGE = "952"  # GS1 dành dải 952 cho demo/thử nghiệm: không bao giờ là tiền tố thật của bệnh viện
# Mã GIAI khắc laser của dụng cụ (FEAT-014 A-06 I8): <prefix>I-<8 số>. Dấu "-" làm dạng này không bao giờ trùng
# Set ID <prefix><mã loại bộ [A-Z0-9]{2,8}><6 số>.
INSTRUMENT_ASSET_PREFIX = "I-"
INSTRUMENT_SERIAL_DIGITS = 8
# Set ID (§5.3.3, FEAT-016 G2): 6 số cuối luôn là số thứ tự, nên mã loại bộ kết thúc bằng số không gây nhập nhằng.
# GIAI (AI 8004) không có check digit: chỉ kiểm tiền tố 4-12 chữ số + CSET 82 + độ dài.
SET_SERIAL_DIGITS = 6
# Mã phiên bản BOM in trên phiếu kiểm đếm (FEAT-015 S8): tham chiếu bất biến tới (loại bộ, phiên bản), không phải GS1,
# không ghi Code Registry. Tiền tố chữ "BOM-" làm mã không bao giờ trùng Set ID (bắt đầu bằng số) hay mã nội bộ.
BOM_CODE_PREFIX = "BOM-"
BOM_MAX_VERSION = 9999

# GS1 AI encodable character set 82 (GS1 General Specifications, Figure 7.11-1)
CSET82 = frozenset(string.ascii_letters + string.digits + "!\"%&'()*+,-./:;<=>?_")

_AIM_PREFIX = re.compile(r"^\][A-Za-z][0-9A-Za-z]")
_GTIN14 = re.compile(r"[0-9]{14}")
_GTIN_BODY = re.compile(r"[0-9]{13}")
# Cycle ID: thứ tự AI cố định 01 → 11 → 17 → 21, (21) cuối nên chạy tới hết dữ liệu (không cần GS)
_PACK_HRI = re.compile(r"\(01\)([0-9]{14})\(11\)([0-9]{6})\(17\)([0-9]{6})\(21\)(.+)")
_PACK_PLAIN = re.compile(r"01([0-9]{14})11([0-9]{6})17([0-9]{6})21(.+)")
_INSTRUMENT_ASSET = re.compile(r"I-[0-9]{8}")
_INSTRUMENT_GIAI = re.compile(r"[0-9]{4,12}I-[0-9]{8}")
_SET_TYPE_CODE = re.compile(r"[A-Z0-9]{2,8}")
_BOM_CODE = re.compile(
	r"BOM-([A-Z0-9]{2,8})-V([1-9][0-9]{0,3})"
)  # dạng chuẩn: số phiên bản không có số 0 đầu
_INTERNAL_CODES = (
	("employee", re.compile(r"NV-\d{5}")),
	("equipment", re.compile(r"TB-\d{4}")),
	("location", re.compile(r"KE-\d{4}")),
	("station", re.compile(r"TR-\d{3}")),
	("roll", re.compile(r"CN-\d{5}")),
	("container", re.compile(r"CT-\d{6}-\d{5}")),
	("pack", re.compile(r"CY-\d{6}-(?:T\d{2}-)?\d{4}")),
)


class GS1Error(ValueError):
	def __init__(self, code, message):
		super().__init__(message)
		self.code = code


def configured_company_prefix():
	"""Tiền tố GS1 của bệnh viện từ site_config (``tc_gs1_company_prefix``)."""
	import frappe

	return str(frappe.conf.get("tc_gs1_company_prefix") or DEFAULT_COMPANY_PREFIX)


def make_giai(prefix, asset_ref):
	"""Ghép GIAI = GS1 Company Prefix + Individual Asset Reference (AI 8004)."""
	prefix = prefix or ""
	asset_ref = asset_ref or ""
	if not re.fullmatch(r"\d{4,12}", prefix):
		raise GS1Error("GS1_PREFIX", f"GS1 Company Prefix must be 4-12 digits: {prefix!r}")
	if not asset_ref or not set(asset_ref) <= CSET82:
		raise GS1Error("GS1_ASSET_REF", f"Asset reference must use GS1 CSET 82: {asset_ref!r}")
	giai = prefix + asset_ref
	if len(giai) > MAX_GIAI_LENGTH:
		raise GS1Error("GS1_LENGTH", f"GIAI longer than {MAX_GIAI_LENGTH} characters: {giai!r}")
	return giai


def make_instrument_giai(prefix, serial):
	"""GIAI khắc laser của dụng cụ = tiền tố GS1 + ``I-`` + số thứ tự 8 chữ số (A-06 I8)."""
	limit = 10**INSTRUMENT_SERIAL_DIGITS
	if isinstance(serial, bool) or not isinstance(serial, int) or not 1 <= serial < limit:
		raise GS1Error("GS1_ASSET_REF", f"Instrument serial must be an integer 1..{limit - 1}: {serial!r}")
	return make_giai(prefix, f"{INSTRUMENT_ASSET_PREFIX}{serial:0{INSTRUMENT_SERIAL_DIGITS}d}")


def make_bom_code(type_code, version):
	"""Mã phiên bản BOM ``BOM-<TYPE_CODE>-V<n>`` (vd ``BOM-KHAM01-V3``) cho DataMatrix phiếu kiểm đếm (FEAT-015 S8).

	`type_code` đúng ``[A-Z0-9]{2,8}`` (mã loại bộ), `version` số nguyên 1..9999; sai → ``GS1Error`` (``ValueError``).
	"""
	if not isinstance(type_code, str) or not _SET_TYPE_CODE.fullmatch(type_code):
		raise GS1Error("BOM_CODE", f"Set type code must be 2-8 characters A-Z, 0-9: {type_code!r}")
	if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= BOM_MAX_VERSION:
		raise GS1Error("BOM_CODE", f"BOM version must be an integer 1..{BOM_MAX_VERSION}: {version!r}")
	return f"{BOM_CODE_PREFIX}{type_code}-V{version}"


def split_set_id(giai, type_code, prefix=None):
	"""Tách Set ID ``<tiền tố 4-12 số><TYPE_CODE><6 số>`` thành ``(tiền tố, serial)`` (FEAT-016 G2).

	Set ID phải là GIAI hợp lệ (CSET 82, ≤ 30 ký tự), kết thúc bằng `type_code` (``[A-Z0-9]{2,8}``) + 6 chữ số; phần
	trước là tiền tố 4-12 chữ số và bằng `prefix` khi truyền. GIAI không có check digit nên không kiểm thêm gì.
	Sai → ``GS1Error("GS1_SET_ID", …)``.
	"""
	if not isinstance(type_code, str) or not _SET_TYPE_CODE.fullmatch(type_code):
		raise GS1Error("GS1_SET_ID", f"Set type code must be 2-8 characters A-Z, 0-9: {type_code!r}")
	if not isinstance(giai, str) or not _is_valid_giai(giai):
		raise GS1Error("GS1_SET_ID", f"Set ID is not a valid GIAI: {giai!r}")
	suffix = len(type_code) + SET_SERIAL_DIGITS
	head, code, serial = giai[:-suffix], giai[-suffix:-SET_SERIAL_DIGITS], giai[-SET_SERIAL_DIGITS:]
	if (
		code != type_code
		or not re.fullmatch(r"[0-9]{4,12}", head)
		or not re.fullmatch(rf"[0-9]{{{SET_SERIAL_DIGITS}}}", serial)
	):
		raise GS1Error("GS1_SET_ID", f"Set ID {giai!r} does not match <prefix>{type_code}<6 digits>")
	if prefix is not None and head != prefix:
		raise GS1Error("GS1_SET_ID", f"Set ID {giai!r} does not start with GS1 Company Prefix {prefix!r}")
	return head, serial


def is_demo_prefix(prefix):
	"""``True`` nếu tiền tố (hoặc mã bắt đầu bằng tiền tố) thuộc dải demo GS1 ``952`` (OQ-05, D6)."""
	return isinstance(prefix, str) and prefix.startswith(DEMO_PREFIX_RANGE)


def giai_hri(giai):
	"""Chuỗi người đọc in dưới DataMatrix."""
	return f"({AI_GIAI}){giai}"


def giai_payload(giai):
	"""Dữ liệu DataMatrix GS1: FNC1 + AI 8004 + GIAI."""
	return f"{GS}{AI_GIAI}{giai}"


def _is_valid_giai(value):
	return (
		5 <= len(value) <= MAX_GIAI_LENGTH and re.match(r"\d{4}", value) is not None and set(value) <= CSET82
	)


def gtin_check_digit(body13):
	"""Chữ số kiểm tra GTIN-14 từ 13 chữ số đầu (trọng số 3,1,3,… từ trái qua)."""
	if not isinstance(body13, str) or not _GTIN_BODY.fullmatch(body13):
		raise GS1Error("GS1_GTIN", f"GTIN-14 body must be 13 digits: {body13!r}")
	total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(body13))
	return str((10 - total % 10) % 10)


def is_valid_gtin14(value):
	"""``True`` nếu ``value`` là chuỗi đúng 14 chữ số và chữ số cuối là check digit đúng."""
	return (
		isinstance(value, str)
		and _GTIN14.fullmatch(value) is not None
		and gtin_check_digit(value[:13]) == value[13]
	)


def make_test_gtin14(serial):
	"""GTIN-14 TEST: ``0`` + prefix demo + serial 5 chữ số + check digit.

	Chỉ devdata/test gọi (D6): GTIN thật do R10 nhập, luôn dùng prefix demo
	``DEFAULT_COMPANY_PREFIX`` bất kể cấu hình site để không lẫn với GTIN thật.
	"""
	if isinstance(serial, bool) or not isinstance(serial, int) or not 1 <= serial <= 99999:
		raise GS1Error("GS1_ITEM_REF", f"Test GTIN serial must be an integer 1..99999: {serial!r}")
	body = "0" + DEFAULT_COMPANY_PREFIX + f"{serial:05d}"
	return body + gtin_check_digit(body)


def is_test_gtin(gtin):
	"""``True`` nếu GTIN thuộc dải TEST (``0952…``) — nhãn phải in dòng ``TEST``."""
	return isinstance(gtin, str) and gtin.startswith(TEST_GTIN_PREFIX)


def _is_valid_serial(value):
	return isinstance(value, str) and 1 <= len(value) <= MAX_SERIAL_LENGTH and set(value) <= CSET82


def _as_date(value):
	if isinstance(value, datetime):
		value = value.date()
	if not isinstance(value, date) or not 2000 <= value.year <= 2099:
		raise GS1Error("GS1_DATES", f"Date must be a date within 2000..2099: {value!r}")
	return value


def _yymmdd(value):
	return f"{value.year % 100:02d}{value.month:02d}{value.day:02d}"


def _parse_yymmdd(text):
	try:
		return date(2000 + int(text[:2]), int(text[2:4]), int(text[4:]))
	except ValueError:
		return None


def _cycle_elements(gtin, packed, expiry, cycle_id):
	"""Kiểm dữ liệu Cycle ID và trả ``(gtin, YYMMDD đóng gói, YYMMDD hạn, cycle_id)``."""
	if not is_valid_gtin14(gtin):
		raise GS1Error("GS1_GTIN", f"Invalid GTIN-14: {gtin!r}")
	if not _is_valid_serial(cycle_id):
		raise GS1Error(
			"GS1_SERIAL", f"Cycle ID must be 1-{MAX_SERIAL_LENGTH} characters of GS1 CSET 82: {cycle_id!r}"
		)
	packed, expiry = _as_date(packed), _as_date(expiry)
	if expiry < packed:
		raise GS1Error("GS1_DATES", f"Expiry {expiry} is before packed date {packed}")
	return gtin, _yymmdd(packed), _yymmdd(expiry), cycle_id


def make_cycle_payload(gtin, packed, expiry, cycle_id):
	"""Dữ liệu DataMatrix Cycle ID: FNC1 + (01) GTIN-14 + (11) đóng gói + (17) hạn + (21) Cycle ID.

	(21) là AI cuối nên không có GS phía sau.
	"""
	gtin, packed, expiry, cycle_id = _cycle_elements(gtin, packed, expiry, cycle_id)
	return f"{GS}{AI_GTIN}{gtin}{AI_PACKED}{packed}{AI_EXPIRY}{expiry}{AI_SERIAL}{cycle_id}"


def cycle_hri(gtin, packed, expiry, cycle_id):
	"""Chuỗi người đọc in dưới DataMatrix Cycle ID."""
	gtin, packed, expiry, cycle_id = _cycle_elements(gtin, packed, expiry, cycle_id)
	return f"({AI_GTIN}){gtin}({AI_PACKED}){packed}({AI_EXPIRY}){expiry}({AI_SERIAL}){cycle_id}"


def clean_scan(raw):
	"""Bỏ khoảng trắng/CR/LF/Tab hai đầu, tiền tố AIM (``]d2``, ``]Q1``…) và FNC1 (GS) đầu/cuối.

	GS đứng trước tiền tố AIM (máy quét chèn FNC1 trước khi truyền) cũng được bỏ.
	"""
	value = (raw or "").strip(GS + " \t\r\n")
	value = _AIM_PREFIX.sub("", value)
	return value.strip(GS + " \t\r\n")


def _parse_pack_payload(value):
	"""Nhận dạng payload Cycle ID đã làm sạch (dạng HRI hoặc dạng liền); sai cấu trúc → ``None``."""
	match = _PACK_HRI.fullmatch(value) or _PACK_PLAIN.fullmatch(value)
	if match is None:
		return None
	gtin, packed_text, expiry_text, cycle_id = match.groups()
	packed, expiry = _parse_yymmdd(packed_text), _parse_yymmdd(expiry_text)
	if not is_valid_gtin14(gtin) or not _is_valid_serial(cycle_id):
		return None
	if packed is None or expiry is None or expiry < packed:
		return None
	return {"type": "pack", "id": cycle_id, "raw": value, "gtin": gtin, "packed": packed, "expiry": expiry}


def parse_scan(raw, company_prefix=None):
	"""Nhận dạng chuỗi quét: Set ID GIAI, mã GIAI dụng cụ, Cycle ID (GS1 hoặc ``CY-…``) hoặc mã QR nội bộ (§5.3.3).

	Trả ``{"type": ..., "id": ..., "raw": ...}``; không nhận ra → ``type = "unknown"``. Mã dụng cụ
	``<prefix>I-<8 số>`` → ``type = "instrument"`` (có AI 8004 thì nhận theo dạng; không AI thì phần sau tiền tố
	cấu hình phải đúng ``I-<8 số>``). Các loại mã cũ giữ nguyên kết quả.
	Nhãn gói dạng GS1 (01)(11)(17)(21) trả thêm ``gtin``, ``packed``, ``expiry`` (``datetime.date``).
	Mã phiên bản BOM của phiếu kiểm đếm ``BOM-<TYPE_CODE>-V<n>`` → ``type = "bom"`` kèm ``set_type``, ``bom_version``.
	"""
	value = clean_scan(raw)
	# raw bị cắt: chuỗi quét đi vào Audit Log (append-only) nên không được dài tùy ý
	unknown = {"type": "unknown", "id": None, "raw": value[:MAX_SCAN_LENGTH]}
	if not value or len(value) > MAX_SCAN_LENGTH:
		return unknown

	pack = _parse_pack_payload(value)
	if pack is not None:
		return pack

	giai = None
	if value.startswith(f"({AI_GIAI})"):
		giai = value[len(AI_GIAI) + 2 :]
	elif value.startswith(AI_GIAI):
		giai = value[len(AI_GIAI) :].split(GS, 1)[0]
	if giai is not None:
		if _INSTRUMENT_GIAI.fullmatch(giai):
			return {"type": "instrument", "id": giai, "raw": value}
		return {"type": "set", "id": giai, "raw": value} if _is_valid_giai(giai) else unknown

	for kind, pattern in _INTERNAL_CODES:
		if pattern.fullmatch(value):
			return {"type": kind, "id": value, "raw": value}

	bom = _BOM_CODE.fullmatch(value)
	if bom is not None:
		return {
			"type": "bom",
			"id": value,
			"set_type": bom.group(1),
			"bom_version": int(bom.group(2)),
			"raw": value,
		}

	prefix = configured_company_prefix() if company_prefix is None else company_prefix
	if prefix and value.startswith(prefix) and _INSTRUMENT_ASSET.fullmatch(value[len(prefix) :]):
		return {"type": "instrument", "id": value, "raw": value}
	if prefix and value.startswith(prefix) and _is_valid_giai(value):
		return {"type": "set", "id": value, "raw": value}
	return unknown


def encode_datamatrix_png(payload, module_px=6, margin_px=12):
	"""Mã hóa DataMatrix ECC200 thành ảnh PNG; ký tự GS được mã hóa thành FNC1."""
	from PIL import Image
	from pylibdmtx.wrapper import (
		DmtxProperty,
		c_ubyte_p,
		dmtxEncodeCreate,
		dmtxEncodeDataMatrix,
		dmtxEncodeDestroy,
		dmtxEncodeSetProp,
		dmtxImageGetProp,
	)

	data = payload.encode("ascii")
	encoder = dmtxEncodeCreate()
	if not encoder:
		raise GS1Error("DMTX_ENCODER", "Could not create DataMatrix encoder")
	try:
		dmtxEncodeSetProp(encoder, DmtxProperty.DmtxPropFnc1, ord(GS))
		dmtxEncodeSetProp(encoder, DmtxProperty.DmtxPropModuleSize, module_px)
		dmtxEncodeSetProp(encoder, DmtxProperty.DmtxPropMarginSize, margin_px)
		if dmtxEncodeDataMatrix(encoder, len(data), cast(data, c_ubyte_p)) == 0:
			raise GS1Error("DMTX_ENCODE", "Could not encode DataMatrix payload")
		image = encoder[0].image
		width, height, bpp = (
			dmtxImageGetProp(image, prop)
			for prop in (
				DmtxProperty.DmtxPropWidth,
				DmtxProperty.DmtxPropHeight,
				DmtxProperty.DmtxPropBitsPerPixel,
			)
		)
		size = width * height * bpp // 8
		pixels = ctypes.string_at(cast(image[0].pxl, ctypes.POINTER(ctypes.c_ubyte * size)), size)
	finally:
		dmtxEncodeDestroy(byref(encoder))

	buffer = io.BytesIO()
	Image.frombytes("RGB", (width, height), pixels).save(buffer, format="PNG")
	return buffer.getvalue()


def decode_datamatrix_png(png):
	"""Giải mã DataMatrix từ ảnh PNG (FNC1 trả về dạng GS) — dùng cho kiểm tra nhãn."""
	from PIL import Image
	from pylibdmtx import pylibdmtx
	from pylibdmtx.wrapper import DmtxProperty, c_ubyte_p, dmtxDecodeSetProp

	image = Image.open(io.BytesIO(png)).convert("RGB")
	pixels, width, height, bpp = pylibdmtx._pixel_data(image)
	with pylibdmtx._image(cast(pixels, c_ubyte_p), width, height, pylibdmtx._PACK_ORDER[bpp]) as img:
		with pylibdmtx._decoder(img, 1) as decoder:
			dmtxDecodeSetProp(decoder, DmtxProperty.DmtxPropFnc1, ord(GS))
			with pylibdmtx._region(decoder, None) as region:
				if not region:
					raise GS1Error("DMTX_DECODE", "No DataMatrix found in image")
				decoded = pylibdmtx._decode_region(decoder, region, pylibdmtx.DmtxUndefined, 1)
	if not decoded:
		raise GS1Error("DMTX_DECODE", "Could not decode DataMatrix")
	return decoded.data.decode("ascii")


def zpl_datamatrix(payload, x, y, module_dots=6):
	"""Lệnh ZPL in DataMatrix ECC200 (máy in tự mã hóa); FNC1 = ``_1``."""
	if "^" in payload or "~" in payload:
		raise GS1Error("ZPL_CHAR", "Payload must not contain ZPL control characters")
	data = payload.replace("_", "__").replace(GS, "_1")
	return f"^FO{x},{y}^BXN,{module_dots},200,0,0,1,_,1^FD{data}^FS"
