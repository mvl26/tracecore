"""Sinh và phân tích mã GS1 cho TraceCore (ADR-004).

Nơi duy nhất tạo Set ID GIAI (AI 8004), phân tích chuỗi quét từ máy quét HID
và mã hóa DataMatrix (ảnh PNG qua libdmtx, lệnh ZPL ``^BXN`` cho máy in).
Hàm ở đây thuần Python, không đọc/ghi DB.
"""

import ctypes
import io
import re
import string
from ctypes import byref, cast

GS = "\x1d"  # FNC1 trong chuỗi dữ liệu (GS1 dùng GS làm FNC1 / phân cách AI)
AI_GIAI = "8004"
DEFAULT_COMPANY_PREFIX = "9520000"  # prefix GS1 "952" dành cho demo — chỉ dev/staging (OQ-05)
MAX_GIAI_LENGTH = 30
MAX_SCAN_LENGTH = 120

# GS1 AI encodable character set 82 (GS1 General Specifications, Figure 7.11-1)
CSET82 = frozenset(string.ascii_letters + string.digits + "!\"%&'()*+,-./:;<=>?_")

_AIM_PREFIX = re.compile(r"^\][A-Za-z][0-9A-Za-z]")
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


def _clean(raw):
	value = (raw or "").strip(" \t\r\n")
	value = _AIM_PREFIX.sub("", value)
	return value.strip(GS + " \t\r\n")


def parse_scan(raw, company_prefix=None):
	"""Nhận dạng chuỗi quét: Set ID GIAI hoặc mã QR nội bộ (§5.3.3).

	Trả ``{"type": ..., "id": ..., "raw": ...}``; không nhận ra → ``type = "unknown"``.
	"""
	value = _clean(raw)
	unknown = {"type": "unknown", "id": None, "raw": value}
	if not value or len(value) > MAX_SCAN_LENGTH:
		return unknown

	giai = None
	if value.startswith(f"({AI_GIAI})"):
		giai = value[len(AI_GIAI) + 2 :]
	elif value.startswith(AI_GIAI):
		giai = value[len(AI_GIAI) :].split(GS, 1)[0]
	if giai is not None:
		return {"type": "set", "id": giai, "raw": value} if _is_valid_giai(giai) else unknown

	for kind, pattern in _INTERNAL_CODES:
		if pattern.fullmatch(value):
			return {"type": kind, "id": value, "raw": value}

	prefix = configured_company_prefix() if company_prefix is None else company_prefix
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
