"""PDF nhãn mã mẻ/lô cho máy trạm tự lưu (A-99): chỉ đọc, không tạo Print Job.

`render` dựng nhãn khổ nhỏ gồm QR (cùng `core.qr.qr_png` với hình trên màn, cùng nội dung mã) và các dòng chữ, sinh PDF
trong bộ nhớ bằng wkhtmltopdf của Frappe, trả ``{"pdf_b64", "filename"}``. wkhtmltopdf không hiểu biến CSS nên giá trị
token ``--tc-*`` được thay thẳng vào HTML; kích thước theo mm vì đây là khổ giấy in, không phải màn hình. Frappe đọc lề
trang từ CSS ``.print-format``: không khai thì lề trên mặc định 15 mm làm nhãn tràn sang trang sau.
"""

import base64
import re

import frappe
from frappe.utils import escape_html

from tracecore.core import qr

PAGE_WIDTH_MM = 80
PAGE_HEIGHT_MM = 45
QR_MM = 36
DATETIME_FORMAT = "%d/%m/%Y %H:%M"
_TOKENS = ("label-ink", "card", "font-sans", "font-mono")


def _tokens():
	path = frappe.get_app_path("tracecore", "public", "css", "tokens.css")
	with open(path, encoding="utf-8") as handle:
		css = handle.read()
	return {name: re.search(rf"--tc-{name}:\s*([^;]+);", css).group(1).strip() for name in _TOKENS}


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
	from frappe.utils.pdf import get_pdf

	options = {
		"page-width": f"{PAGE_WIDTH_MM}mm",
		"page-height": f"{PAGE_HEIGHT_MM}mm",
		"image-quality": "100",  # dưới 100 wkhtmltopdf nén QR thành JPEG, viền module không còn sắc
	}
	pdf = get_pdf(render_html(code, title, lines), options)
	return {"pdf_b64": base64.b64encode(pdf).decode("ascii"), "filename": f"{code}.pdf"}
