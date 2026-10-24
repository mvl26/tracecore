"""Ảnh PNG xem trước nhãn DataMatrix (core.print, tách khỏi `print.py` ở FEAT-016 để giữ file ≤ 650 dòng).

- `datamatrix_preview_png`: vẽ DataMatrix của payload + các dòng chữ lên khung trắng đúng kích thước nhãn (dot).
- `zpl_preview_png`: dựng ảnh từ chính ZPL đã render (vị trí DataMatrix ``^FO…^BXN`` và các ô chữ
  ``^FO…^A0N…[^FB…]^FD…^FS``), nên ảnh theo đúng mẫu R10 đang dùng. Ảnh chỉ để xem: chữ vẽ bằng phông mặc định của
  Pillow (nơi gọi truyền ZPL đã bỏ dấu), máy in dùng ZPL.
- Nhãn thử của trạm (`label_layout`, kích thước 50 x 30 mm).
"""

import io
import re

from tracecore.core import gs1

LABEL_WIDTH_DOTS = 590  # 50 mm ở 300 dpi
LABEL_HEIGHT_DOTS = 354  # 30 mm ở 300 dpi
DM_ORIGIN = (30, 40)
PREVIEW_MODULE_PX = 6
PREVIEW_MARGIN_PX = 12
MAX_PREVIEW_MODULE_PX = 12

_ZPL_DATAMATRIX = re.compile(r"\^FO(\d+),(\d+)\^BXN,(\d+)")
_ZPL_TEXT = re.compile(r"\^FO(\d+),(\d+)\^A0N,(\d+),\d+(?:\^FB(\d+),(\d+),(\d+),[LCRJ],\d+)?\^FD(.*?)\^FS")


def label_layout(giai, station):
	"""Các dòng chữ của nhãn thử: (x, y, cỡ chữ theo dot, nội dung ASCII).

	Cột phải cạnh DataMatrix cho tiêu đề/trạm; chuỗi người đọc (8004)… chạy hết bề ngang ở đáy nhãn.
	"""
	return [
		(200, 50, 34, "TraceCore TEST"),
		(200, 110, 28, f"Station {station}"),
		(30, 290, 24, gs1.giai_hri(giai)),
	]


def datamatrix_preview_png(payload, lines, size, origin=DM_ORIGIN, module_px=PREVIEW_MODULE_PX):
	"""PNG `size` = (rộng, cao) dot: DataMatrix của `payload` dán tại `origin` (góc ảnh mã, gồm lề trắng), các dòng chữ
	`lines` = [(x, y, cỡ chữ, nội dung)] bằng phông mặc định của Pillow."""
	from PIL import Image, ImageDraw, ImageFont

	canvas = Image.new("RGB", tuple(size), "white")
	symbol = gs1.encode_datamatrix_png(payload, module_px=module_px, margin_px=PREVIEW_MARGIN_PX)
	canvas.paste(Image.open(io.BytesIO(symbol)), tuple(origin))
	draw = ImageDraw.Draw(canvas)
	for x, y, font_size, text in lines:
		draw.text((x, y), text, fill="black", font=ImageFont.load_default(size=font_size))
	buffer = io.BytesIO()
	canvas.save(buffer, format="PNG")
	return buffer.getvalue()


def _wrap(text, font_size, block_width, max_lines):
	"""Ngắt `text` theo bề rộng ô ``^FB`` (ước lượng bằng phông Pillow), tối đa `max_lines` dòng."""
	from PIL import ImageFont

	font = ImageFont.load_default(size=font_size)
	lines, current = [], ""
	for word in text.split(" "):
		candidate = f"{current} {word}".strip()
		if current and font.getlength(candidate) > block_width:
			lines.append(current)
			current = word
		else:
			current = candidate
	lines.append(current)
	return lines[:max_lines]


def zpl_lines(zpl):
	"""Các dòng chữ (x, y, cỡ chữ, nội dung) của ZPL đã render; ô ``^FB`` được ngắt dòng như máy in (ước lượng)."""
	lines = []
	for x, y, font_size, block, max_lines, spacing, text in _ZPL_TEXT.findall(zpl):
		x, y, font_size = int(x), int(y), int(font_size)
		parts = _wrap(text, font_size, int(block), int(max_lines)) if block else [text]
		step = font_size + (int(spacing) if block else 0)
		lines += [(x, y + index * step, font_size, part) for index, part in enumerate(parts)]
	return lines


def zpl_preview_png(zpl, payload, size):
	"""PNG xem trước từ ZPL đã render: DataMatrix ở vị trí và cỡ module của ``^BXN`` đầu tiên, chữ theo `zpl_lines`."""
	found = _ZPL_DATAMATRIX.search(zpl)
	x, y, module = (int(value) for value in found.groups()) if found else (*DM_ORIGIN, PREVIEW_MODULE_PX)
	origin = (max(0, x - PREVIEW_MARGIN_PX), max(0, y - PREVIEW_MARGIN_PX))
	module = min(max(module, 1), MAX_PREVIEW_MODULE_PX)  # mẫu R10 có thể ghi cỡ module bất thường
	return datamatrix_preview_png(payload, zpl_lines(zpl), size, origin=origin, module_px=module)
