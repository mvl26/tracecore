"""QR nội bộ cho mã đối tượng `NV-`, `TB-`, `KE-`, `TR-`, `CN-`… (ADR-004, A-05 R5).

Payload QR = mã trần (không tiền tố AI). Ảnh PNG xem trước mã hóa bằng PyQRCode, vẽ bằng Pillow;
máy in Zebra tự mã hóa qua lệnh ZPL ``^BQN`` với cùng payload và cùng mức sửa lỗi (``ERROR_LEVEL``).
`decode_png` là bộ giải tối thiểu chỉ dùng để kiểm nhãn/test: đọc ma trận từ ảnh sạch, giải dữ liệu
rồi mã hóa lại bằng PyQRCode và so ma trận — không sửa lỗi Reed-Solomon, không thêm phụ thuộc.
Hàm ở đây thuần Python, không đọc/ghi DB.
"""

import io

ERROR_LEVEL = "M"  # mức sửa lỗi QR (~15 %), dùng chung cho PNG và ZPL
MAX_MAGNIFICATION = 10  # ^BQ cho phép phóng đại 1-10
_ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
_MODE_NUMERIC, _MODE_ALNUM, _MODE_BYTE = 0b0001, 0b0010, 0b0100


class QRError(ValueError):
	def __init__(self, code, message):
		super().__init__(message)
		self.code = code


def _check_payload(payload):
	if not isinstance(payload, str) or not payload:
		raise QRError("QR_PAYLOAD", f"QR payload must be a non-empty string: {payload!r}")


def matrix(payload, error=ERROR_LEVEL, version=None):
	"""Ma trận module QR (list hàng, 1 = đen, không gồm vùng lặng) theo PyQRCode."""
	import pyqrcode

	_check_payload(payload)
	try:
		code = pyqrcode.create(payload, error=error, version=version)
	except ValueError as exc:
		raise QRError("QR_ENCODE", f"Could not encode QR payload: {exc}") from exc
	return [list(row) for row in code.code]


def qr_png(payload, module_px=8, margin_px=16):
	"""Ảnh PNG đen trắng của QR: mỗi module ``module_px`` điểm ảnh, lề trắng ``margin_px`` mỗi phía."""
	from PIL import Image, ImageDraw

	if isinstance(module_px, bool) or not isinstance(module_px, int) or module_px < 1:
		raise QRError("QR_SIZE", f"module_px must be a positive integer: {module_px!r}")
	if isinstance(margin_px, bool) or not isinstance(margin_px, int) or margin_px < 0:
		raise QRError("QR_SIZE", f"margin_px must be a non-negative integer: {margin_px!r}")
	rows = matrix(payload)
	size = len(rows) * module_px + 2 * margin_px
	image = Image.new("1", (size, size), 1)
	draw = ImageDraw.Draw(image)
	for r, row in enumerate(rows):
		for c, dark in enumerate(row):
			if dark:
				x, y = margin_px + c * module_px, margin_px + r * module_px
				draw.rectangle((x, y, x + module_px - 1, y + module_px - 1), fill=0)
	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	return buffer.getvalue()


def zpl_qr(payload, x, y, magnification=6):
	"""Lệnh ZPL in QR model 2 (máy in tự mã hóa), mức sửa lỗi ``ERROR_LEVEL``, nhập dữ liệu tự động.

	Mọi tham số đi thẳng vào lệnh ZPL nên được kiểm chặt: payload là ASCII in được, không có ``^``/``~``
	(mã đối tượng luôn là ASCII); ``x``, ``y`` là số nguyên không âm; ``magnification`` 1-10.
	"""
	_check_payload(payload)
	if "^" in payload or "~" in payload:
		raise QRError("ZPL_CHAR", "Payload must not contain ZPL control characters")
	if not all(" " <= char <= "}" for char in payload):
		raise QRError("ZPL_CHAR", f"Payload must be printable ASCII: {payload!r}")
	for axis, value in (("x", x), ("y", y)):
		if isinstance(value, bool) or not isinstance(value, int) or value < 0:
			raise QRError("QR_POSITION", f"{axis} must be a non-negative integer: {value!r}")
	if isinstance(magnification, bool) or not isinstance(magnification, int):
		raise QRError("QR_SIZE", f"Magnification must be an integer: {magnification!r}")
	if not 1 <= magnification <= MAX_MAGNIFICATION:
		raise QRError("QR_SIZE", f"Magnification must be 1-{MAX_MAGNIFICATION}: {magnification!r}")
	return f"^FO{x},{y}^BQN,2,{magnification}^FD{ERROR_LEVEL}A,{payload}^FS"


def png_matrix(png):
	"""Đọc ma trận module từ ảnh PNG QR sạch (một mã, nền trắng); không thấy QR → ``QRError``."""
	from PIL import Image

	image = Image.open(io.BytesIO(png)).convert("L")
	binary = image.point(lambda v: 255 if v < 128 else 0)
	bbox = binary.getbbox()
	if not bbox:
		raise QRError("QR_DECODE", "No QR code found in image")
	left, top, right, bottom = bbox
	pixels = binary.load()
	run = 0  # hàng trên cùng của mẫu định vị trái-trên: 7 module đen liền
	while left + run < right and pixels[left + run, top]:
		run += 1
	module = run / 7
	n = round((right - left) / module) if module else 0
	if n < 21 or (n - 17) % 4 or abs((bottom - top) - (right - left)) > module:
		raise QRError("QR_DECODE", "Image does not contain a QR symbol")
	return [
		[1 if pixels[int(left + (c + 0.5) * module), int(top + (r + 0.5) * module)] else 0 for c in range(n)]
		for r in range(n)
	]


def _function_modules(version):
	"""Ô thuộc mẫu chức năng (định vị, phân cách, thông tin định dạng/phiên bản, định thời, căn chỉnh)."""
	from pyqrcode import tables

	n = 17 + 4 * version
	marked = [[False] * n for _ in range(n)]

	def mark(r0, c0, height, width):
		for r in range(max(r0, 0), min(r0 + height, n)):
			for c in range(max(c0, 0), min(c0 + width, n)):
				marked[r][c] = True

	mark(0, 0, 9, 9)
	mark(0, n - 8, 9, 8)
	mark(n - 8, 0, 8, 9)  # gồm cả module tối cố định (n-8, 8)
	for i in range(n):
		marked[6][i] = marked[i][6] = True
	centers = tables.position_adjustment[version] or []
	corners = {(6, 6), (6, n - 7), (n - 7, 6)}
	for r in centers:
		for c in centers:
			if (r, c) not in corners:
				mark(r - 2, c - 2, 5, 5)
	if version >= 7:
		mark(0, n - 11, 6, 3)
		mark(n - 11, 0, 3, 6)
	return marked


def _read_codewords(rows, version, mask):
	from pyqrcode import tables

	n = len(rows)
	marked = _function_modules(version)
	pattern = tables.mask_patterns[mask]
	bits = []
	col, upward = n - 1, True
	while col > 0:
		if col == 6:
			col -= 1
		for r in range(n - 1, -1, -1) if upward else range(n):
			for c in (col, col - 1):
				if not marked[r][c]:
					bits.append(rows[r][c] ^ int(pattern(r, c)))
		upward, col = not upward, col - 2
	return [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits) - 7, 8)]


def _data_codewords(codewords, version, error):
	from pyqrcode import tables

	_ecc, blocks1, size1, blocks2, size2 = tables.eccwbi[version][error]
	sizes = [size1] * blocks1 + [size2] * blocks2
	blocks = [[] for _ in sizes]
	stream = iter(codewords)
	for i in range(max(sizes)):
		for block, size in zip(blocks, sizes, strict=True):
			if i < size:
				block.append(next(stream))
	return [cw for block in blocks for cw in block]


def _parse_data(data, version):
	bits = "".join(f"{cw:08b}" for cw in data)
	pos = 0

	def take(count):
		nonlocal pos
		if pos + count > len(bits):
			raise QRError("QR_DECODE", "QR data stream truncated")
		value = int(bits[pos : pos + count], 2)
		pos += count
		return value

	group = 0 if version <= 9 else 1 if version <= 26 else 2
	length_bits = {_MODE_NUMERIC: (10, 12, 14), _MODE_ALNUM: (9, 11, 13), _MODE_BYTE: (8, 16, 16)}
	text = []
	while len(bits) - pos >= 4:
		mode = take(4)
		if mode == 0:
			break
		if mode not in length_bits:
			raise QRError("QR_DECODE", f"Unsupported QR mode {mode:04b}")
		count = take(length_bits[mode][group])
		if mode == _MODE_NUMERIC:
			while count:
				digits = min(count, 3)
				text.append(f"{take((10, 4, 7)[digits % 3]):0{digits}d}")
				count -= digits
		elif mode == _MODE_ALNUM:
			while count >= 2:
				value = take(11)
				if value >= 45 * 45:
					raise QRError("QR_DECODE", "Invalid alphanumeric QR data")
				text.append(_ALNUM[value // 45] + _ALNUM[value % 45])
				count -= 2
			if count:
				text.append(_ALNUM[take(6) % 45])
		else:
			raw = bytes(take(8) for _ in range(count))
			try:
				text.append(raw.decode("utf-8"))
			except UnicodeDecodeError:
				text.append(raw.decode("iso-8859-1"))
	return "".join(text)


def decode_png(png):
	"""Giải QR từ ảnh PNG sạch (vd từ `qr_png`) — chỉ cho test/kiểm nhãn.

	Thử từng mức sửa lỗi/mặt nạ, nhận kết quả khi mã hóa lại bằng PyQRCode ra đúng ma trận trong ảnh.
	"""
	rows = png_matrix(png)
	version = (len(rows) - 17) // 4
	for error in "LMQH":
		for mask in range(8):
			try:
				data = _data_codewords(_read_codewords(rows, version, mask), version, error)
				text = _parse_data(data, version)
				if text and matrix(text, error=error, version=version) == rows:
					return text
			except (QRError, StopIteration):
				continue
	raise QRError("QR_DECODE", "Could not decode QR code")
