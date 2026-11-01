"""PDF nhãn cho máy trạm tự lưu (A-99, A-101): mẻ/lô (QR) và gói T4 (DataMatrix GS1). Sinh PDF, không đụng Print Job.

Nơi gọi kiểm trạm có máy in (A-100) rồi ghi Print Job sau khi có PDF (`core.print.mark_file_output`).

Nhãn dựng khổ nhỏ, sinh PDF trong bộ nhớ bằng wkhtmltopdf của Frappe. wkhtmltopdf không hiểu biến CSS nên giá trị token
``--tc-*`` được thay thẳng vào HTML; kích thước theo mm vì đây là khổ giấy in, không phải màn hình. Frappe đọc lề trang từ
CSS ``.print-format``: không khai thì lề trên mặc định 15 mm làm nhãn tràn sang trang sau. Thiếu công cụ sinh PDF hay thư
viện mã vạch thì ném `BlockedError(LABEL_PDF_FAILED)`: chứng từ vẫn giữ, thử lại được.
"""

import base64
import io
import math
import re

import frappe
from frappe import _
from frappe.utils import escape_html

from tracecore.core import gs1, qr
from tracecore.core.errors import Block, BlockedError

PAGE_WIDTH_MM = 80
PAGE_HEIGHT_MM = 45
QR_MM = 36
DATETIME_FORMAT = "%d/%m/%Y %H:%M"
# Nhãn gói nhiều dòng hơn nhãn mẻ/lô; trang cao theo nội dung để không bao giờ cắt chữ (dòng THIẾU có thể rất dài)
PACK_PAGE_WIDTH_MM = 100
PACK_DM_MM = 26
PACK_MIN_HEIGHT_MM = 60
PACK_LINE_MM = 5.5  # wkhtmltopdf vẽ chữ lớn hơn cỡ khai; dư còn hơn cắt
PACK_CHARS_PER_LINE = 45
PACK_MARGIN_MM = 8
_TOKENS = ("label-ink", "card", "font-sans", "font-mono")
_FAILURES = (ImportError, OSError, frappe.ValidationError, gs1.GS1Error)


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


def _pdf(code, html, options):
	"""Bytes PDF của `html`; lỗi công cụ → `LABEL_PDF_FAILED`, không để msgprint lên kiosk."""
	from frappe.utils.pdf import get_pdf

	logged = len(frappe.local.message_log)
	try:
		return get_pdf(html, {**options, "image-quality": "100"})  # dưới 100 wkhtmltopdf nén mã thành JPEG
	except _FAILURES as error:
		del frappe.local.message_log[logged:]
		raise _failed(code, error) from error


def render_html(code, title, lines):
	"""HTML một trang nhãn; `title`, `lines` đã dịch, được escape ở đây."""
	tokens = _tokens()
	image = base64.b64encode(qr.qr_png(code)).decode("ascii")
	rows = "".join(f"<div>{escape_html(line)}</div>" for line in lines)
	return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
.print-format {{ margin-top: 0mm; margin-right: 0mm; margin-bottom: 0mm; margin-left: 0mm; }}
html, body {{ margin: 0; padding: 0; background: {tokens["card"]}; color: {tokens["label-ink"]}; }}
body {{ font-family: {tokens["font-sans"]}; font-size: 9pt; line-height: 1.25; }}
.label {{ width: {PAGE_WIDTH_MM - 4}mm; height: {PAGE_HEIGHT_MM - 4}mm; margin: 2mm; overflow: hidden; }}
.qr {{ float: left; width: {QR_MM}mm; height: {QR_MM}mm; margin-right: 2mm; }}
.code {{ font-family: {tokens["font-mono"]}; font-size: 11pt; font-weight: bold; }}
.title {{ font-weight: bold; }}
</style></head><body><div class="label">
<img class="qr" src="data:image/png;base64,{image}" alt="">
<div class="code">{escape_html(code)}</div>
<div class="title">{escape_html(title)}</div>
{rows}
</div></body></html>"""


def render(code, title, lines):
	"""Trả ``{"pdf_b64", "filename"}``; `code` là tên chứng từ `ME-`/`LR-` nên an toàn làm tên file."""
	options = {"page-width": f"{PAGE_WIDTH_MM}mm", "page-height": f"{PAGE_HEIGHT_MM}mm"}
	return encode(_pdf(code, render_html(code, title, lines), options), f"{code}.pdf")


def encode(pdf, filename):
	return {"pdf_b64": base64.b64encode(pdf).decode("ascii"), "filename": filename}


def _pack_height_mm(rows):
	lines = sum(max(1, math.ceil(len(text) / PACK_CHARS_PER_LINE)) for text, _style in rows)
	return max(PACK_MIN_HEIGHT_MM, math.ceil(lines * PACK_LINE_MM) + PACK_MARGIN_MM)


def pack_html(code, image_b64, rows):
	"""HTML nhãn gói: `rows` là ``[(chữ đã dịch, kiểu)]``, kiểu ``code``, ``mono``, ``title`` hoặc rỗng; escape ở đây."""
	tokens = _tokens()
	body = "".join(f'<div class="{style}">{escape_html(text)}</div>' for text, style in rows)
	return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
.print-format {{ margin-top: 0mm; margin-right: 0mm; margin-bottom: 0mm; margin-left: 0mm; }}
html, body {{ margin: 0; padding: 0; background: {tokens["card"]}; color: {tokens["label-ink"]}; }}
body {{ font-family: {tokens["font-sans"]}; font-size: 9pt; line-height: 1.25; }}
.label {{ width: {PACK_PAGE_WIDTH_MM - 4}mm; margin: 2mm; }}
.dm {{ float: right; width: {PACK_DM_MM}mm; height: {PACK_DM_MM}mm; margin-left: 2mm; }}
.code {{ font-family: {tokens["font-mono"]}; font-size: 11pt; font-weight: bold; }}
.mono {{ font-family: {tokens["font-mono"]}; }}
.title {{ font-weight: bold; }}
</style></head><body><div class="label">
<img class="dm" src="data:image/png;base64,{image_b64}" alt="{escape_html(code)}">
{body}
</div></body></html>"""


def pack_pdf(code, payload, rows):
	"""Bytes PDF một trang của nhãn gói: DataMatrix GS1 sinh tại server từ `payload`, cùng `rows` với bản xem trước T4."""
	try:
		png = gs1.encode_datamatrix_png(payload)
	except _FAILURES as error:
		raise _failed(code, error) from error
	height = _pack_height_mm(rows)
	options = {"page-width": f"{PACK_PAGE_WIDTH_MM}mm", "page-height": f"{height}mm"}
	return _pdf(code, pack_html(code, base64.b64encode(png).decode("ascii"), rows), options)


def merge(pdfs):
	"""Gộp nhiều PDF thành một (trình duyệt có thể chặn nhiều lần tự tải trong một thao tác); một file thì giữ nguyên."""
	from pypdf import PdfWriter

	if len(pdfs) == 1:
		return pdfs[0]
	writer = PdfWriter()
	for pdf in pdfs:
		writer.append(io.BytesIO(pdf))
	output = io.BytesIO()
	writer.write(output)
	return output.getvalue()
