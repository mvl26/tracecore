"""PDF nhãn in qua hộp thoại In của trình duyệt (A-99, A-101, A-114): mọi nhãn cùng một khổ của cuộn nhãn chung.

Khổ lấy từ `TraceCore Settings.label_width_mm` x `label_height_mm` (mặc định 60 x 40 mm, A-114 d). Bố cục: mã vạch
vuông bên trái (QR cho mã đối tượng, lô, mẻ; DataMatrix GS1 cho gói và thẻ bộ), chữ bên phải; cỡ chữ co theo lượng chữ
để không bao giờ sang trang hay cắt dòng THIẾU (FR-M2-06.1). Sinh PDF trong bộ nhớ bằng wkhtmltopdf của Frappe;
wkhtmltopdf không hiểu biến CSS nên giá trị token ``--tc-*`` được thay thẳng vào HTML; kích thước theo mm vì đây là khổ
giấy in. Frappe đọc lề trang từ CSS ``.print-format``: không khai thì lề trên mặc định 15 mm làm nhãn tràn sang trang
sau. Thiếu công cụ sinh PDF hay thư viện mã vạch thì ném `BlockedError(LABEL_PDF_FAILED)`: chứng từ vẫn giữ, thử lại.
"""

import base64
import io
import math
import re

import frappe
from frappe import _
from frappe.utils import escape_html, flt

from tracecore.core import gs1, qr
from tracecore.core.errors import Block, BlockedError

SETTINGS = "TraceCore Settings"
DEFAULT_SIZE_MM = (60, 40)
DATETIME_FORMAT = "%d/%m/%Y %H:%M"
PAD_MM = 1.5
GAP_MM = 1.5
IMAGE_SHARE = 0.45  # mã vạch chiếm tối đa gần nửa bề rộng, phần còn lại cho chữ
MIN_IMAGE_MM, IMAGE_STEP_MM = 14, 2  # DataMatrix GS1 26x26 ở 14 mm vẫn quét được (ô ~0,5 mm)
MAX_PT, MIN_PT, STEP_PT = 9.0, 3.5, 0.5
MM_PER_PT = 25.4 / 72
CHAR_WIDTH_EM = 0.6  # ước lượng dư: wkhtmltopdf vẽ chữ to hơn cỡ khai, dư còn hơn cắt
LINE_HEIGHT_EM = 1.25
_TOKENS = ("label-ink", "card", "font-sans", "font-mono")
_FAILURES = (ImportError, OSError, frappe.ValidationError, gs1.GS1Error)


def label_size():
	"""(rộng, cao) mm của khổ nhãn chung; trống hoặc không dương thì 60 x 40."""
	width = flt(frappe.db.get_single_value(SETTINGS, "label_width_mm"))
	height = flt(frappe.db.get_single_value(SETTINGS, "label_height_mm"))
	return (width if width > 0 else DEFAULT_SIZE_MM[0], height if height > 0 else DEFAULT_SIZE_MM[1])


def _tokens():
	path = frappe.get_app_path("tracecore", "public", "css", "tokens.css")
	with open(path, encoding="utf-8") as handle:
		css = handle.read()
	return {name: re.search(rf"--tc-{name}:\s*([^;]+);", css).group(1).strip() for name in _TOKENS}


def _failed(code, error):
	return BlockedError(
		Block(
			"LABEL_PDF_FAILED",
			_("Label PDF could not be created"),
			_("{0} is kept, but its label PDF could not be created: {1}").format(code, error),
			_("Print again. If it keeps failing, ask R10 to check the PDF tool on the server."),
		)
	)


def _pdf(code, html):
	"""Bytes PDF một trang khổ nhãn chung của `html`; lỗi công cụ → `LABEL_PDF_FAILED`, không để msgprint lên kiosk."""
	from frappe.utils.pdf import get_pdf

	width, height = label_size()
	options = {"page-width": f"{width}mm", "page-height": f"{height}mm", "image-quality": "100"}
	logged = len(frappe.local.message_log)
	try:
		return get_pdf(html, options)  # image-quality dưới 100 thì wkhtmltopdf nén mã thành JPEG
	except _FAILURES as error:
		del frappe.local.message_log[logged:]
		raise _failed(code, error) from error


def _fits(texts, size, text_width_mm, text_height_mm):
	char_mm = size * MM_PER_PT * CHAR_WIDTH_EM
	per_line = max(1, math.floor(text_width_mm / char_mm))
	lines = sum(max(1, math.ceil(len(text) / per_line)) for text in texts)
	return lines * size * MM_PER_PT * LINE_HEIGHT_EM <= text_height_mm


def font_pt(texts, text_width_mm, text_height_mm):
	"""Cỡ chữ lớn nhất (pt) để mọi dòng `texts` xuống dòng vừa khung chữ, hoặc None nếu cỡ nhỏ nhất vẫn không vừa."""
	size = MAX_PT
	while size >= MIN_PT:
		if _fits(texts, size, text_width_mm, text_height_mm):
			return size
		size -= STEP_PT
	return None


def _layout(texts):
	"""(rộng trong, cao trong, cạnh mã vạch, cỡ chữ): mã vạch lớn nhất có thể; chữ quá nhiều (vd danh sách THIẾU dài)
	thì thu mã vạch dần tới `MIN_IMAGE_MM` để nhường chỗ, vì chữ cảnh báo không được cắt (FR-M2-06.1)."""
	width, height = label_size()
	inner_w, inner_h = width - 2 * PAD_MM, height - 2 * PAD_MM
	image = min(inner_h, inner_w * IMAGE_SHARE)
	while True:
		size = font_pt(texts, inner_w - image - GAP_MM, inner_h)
		if size is not None or image <= MIN_IMAGE_MM:
			return inner_w, inner_h, image, size or MIN_PT
		image = max(MIN_IMAGE_MM, image - IMAGE_STEP_MM)


def label_html(code, image_b64, rows):
	"""HTML một nhãn: `rows` là ``[(chữ đã dịch, kiểu)]``, kiểu ``code``, ``mono``, ``title`` hoặc rỗng; escape ở đây."""
	tokens = _tokens()
	inner_w, inner_h, image, size = _layout([text for text, _style in rows])
	body = "".join(f'<div class="{escape_html(style)}">{escape_html(text)}</div>' for text, style in rows)
	return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
.print-format {{ margin-top: 0mm; margin-right: 0mm; margin-bottom: 0mm; margin-left: 0mm; }}
html, body {{ margin: 0; padding: 0; background: {tokens["card"]}; color: {tokens["label-ink"]}; }}
body {{ font-family: {tokens["font-sans"]}; font-size: {size}pt; line-height: {LINE_HEIGHT_EM}; }}
.label {{ width: {inner_w}mm; height: {inner_h}mm; margin: {PAD_MM}mm; overflow: hidden; }}
.img {{ float: left; width: {image}mm; height: {image}mm; margin-right: {GAP_MM}mm; }}
.text {{ overflow: hidden; word-wrap: break-word; }}
.code {{ font-family: {tokens["font-mono"]}; font-weight: bold; }}
.mono {{ font-family: {tokens["font-mono"]}; }}
.title {{ font-weight: bold; }}
</style></head><body><div class="label">
<img class="img" src="data:image/png;base64,{image_b64}" alt="{escape_html(code)}">
<div class="text">{body}</div>
</div></body></html>"""


def _png_b64(code, make_png):
	try:
		return base64.b64encode(make_png()).decode("ascii")
	except _FAILURES as error:
		raise _failed(code, error) from error


def _qr_rows(code, title, lines):
	return [(code, "code"), (title, "title"), *((line, "") for line in lines if line)]


def render_html(code, title, lines):
	"""HTML nhãn QR của chứng từ `code`; `title`, `lines` đã dịch, được escape ở `label_html`."""
	return label_html(code, base64.b64encode(qr.qr_png(code)).decode("ascii"), _qr_rows(code, title, lines))


def qr_pdf(code, title, lines):
	"""Bytes PDF nhãn QR của mã trần `code` (lô rửa, mẻ, thùng chất thải, đối tượng)."""
	image = _png_b64(code, lambda: qr.qr_png(code))
	return _pdf(code, label_html(code, image, _qr_rows(code, title, lines)))


def render(code, title, lines):
	"""Trả ``{"pdf_b64", "filename"}`` nhãn QR; `code` là tên chứng từ `ME-`/`LR-` nên an toàn làm tên file."""
	return encode(qr_pdf(code, title, lines), f"{code}.pdf")


def object_pdf(code, title, subtitle=""):
	"""Bytes PDF nhãn QR đối tượng (máy, trạm, kệ, cuộn, thẻ nhân viên; A-05, A-114)."""
	return qr_pdf(code, title, [subtitle])


def datamatrix_pdf(code, payload, rows):
	"""Bytes PDF nhãn có DataMatrix GS1 sinh tại server từ `payload` (gói Cycle ID, thẻ bộ Set ID) và các dòng `rows`."""
	image = _png_b64(code, lambda: gs1.encode_datamatrix_png(payload))
	return _pdf(code, label_html(code, image, rows))


def pack_html(code, image_b64, rows):
	"""HTML nhãn gói (giữ tên cho nơi gọi cũ): như `label_html`."""
	return label_html(code, image_b64, rows)


def pack_pdf(code, payload, rows):
	"""Bytes PDF một trang của nhãn gói, cùng `rows` với bản xem trước T4."""
	return datamatrix_pdf(code, payload, rows)


def encode(pdf, filename):
	return {"pdf_b64": base64.b64encode(pdf).decode("ascii"), "filename": filename}


def merge(pdfs):
	"""Gộp nhiều PDF thành một (một thao tác in nhiều nhãn chỉ mở một hộp thoại In); một file thì giữ nguyên."""
	from pypdf import PdfWriter

	if len(pdfs) == 1:
		return pdfs[0]
	writer = PdfWriter()
	for pdf in pdfs:
		writer.append(io.BytesIO(pdf))
	output = io.BytesIO()
	writer.write(output)
	return output.getvalue()
