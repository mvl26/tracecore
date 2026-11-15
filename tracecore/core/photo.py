"""Kiểm ảnh chụp gửi từ trạm/PDA (base64) theo nội dung: T1 ảnh bất thường (FEAT-019) và ảnh của màn trạm (A-159).

Không tin tên file hay Content-Type: giải base64, Pillow nhận dạng và ``verify``; chỉ nhận JPEG/PNG/WebP, tối đa
``MAX_BYTES`` byte và ``MAX_PIXELS`` điểm ảnh. Đuôi file lưu lấy theo định dạng thật.
"""

import base64
import binascii
import io

from frappe import _
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


class PhotoError(ValueError):
	"""Ảnh không nhận được; ``str(error)`` là lý do đã dịch để hiện ở alert (kết quả → lý do → hành động)."""


def check_image(content_base64) -> tuple[bytes, str]:
	"""``(bytes, đuôi file)`` của ảnh base64 hợp lệ; ngược lại ném ``PhotoError``."""
	if not isinstance(content_base64, str) or len(content_base64) > MAX_BYTES * 4 // 3 + 16:
		raise PhotoError(_("The photo is missing or larger than 5 MB."))
	try:
		data = base64.b64decode(content_base64, validate=True)
	except (binascii.Error, ValueError):
		raise PhotoError(_("The photo could not be read.")) from None
	if not data or len(data) > MAX_BYTES:
		raise PhotoError(_("The photo is missing or larger than 5 MB."))
	try:
		with Image.open(io.BytesIO(data)) as image:
			extension = FORMATS.get(image.format)
			width, height = image.size
			image.verify()
	except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
		raise PhotoError(_("The file is not a JPEG, PNG or WebP image.")) from None
	if not extension or width * height > MAX_PIXELS:
		raise PhotoError(_("The file is not a JPEG, PNG or WebP image."))
	return data, extension
