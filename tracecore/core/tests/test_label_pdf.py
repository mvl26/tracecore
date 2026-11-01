"""PDF nhãn mã mẻ/lô (A-99): PDF thật từ wkhtmltopdf, QR trong PDF quét ra đúng mã."""

import base64
import io

from frappe.tests.utils import FrappeTestCase
from pypdf import PdfReader

from tracecore.core import label_pdf, qr


def _render(code="ME-261101-02", lines=("Máy tiệt khuẩn 1 - Chương trình 134", "01/11/2026 08:05", "3 gói")):
	result = label_pdf.render(code, "Mẻ tiệt khuẩn", list(lines))
	return result, base64.b64decode(result["pdf_b64"])


class TestLabelPdf(FrappeTestCase):
	def test_output_is_a_real_one_page_small_pdf_named_after_the_code(self):
		result, pdf = _render()
		self.assertEqual(result["filename"], "ME-261101-02.pdf")
		self.assertTrue(pdf.startswith(b"%PDF"))
		reader = PdfReader(io.BytesIO(pdf))
		self.assertEqual(len(reader.pages), 1)
		# khổ nhãn, không phải A4 (842 pt)
		self.assertLess(float(reader.pages[0].mediabox.height), 200)

	def test_qr_in_the_pdf_decodes_back_to_the_code(self):
		for code in ("ME-261101-02", "LR-261101-07"):
			_result, pdf = _render(code)
			images = PdfReader(io.BytesIO(pdf)).pages[0].images
			self.assertEqual(len(images), 1)
			self.assertEqual(qr.decode_png(images[0].data), code)

	def test_qr_is_embedded_lossless(self):
		_result, pdf = _render()
		self.assertTrue(PdfReader(io.BytesIO(pdf)).pages[0].images[0].name.endswith(".png"))

	def test_label_text_is_in_the_pdf(self):
		_result, pdf = _render()
		text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
		for part in ("ME-261101-02", "01/11/2026 08:05", "3 g"):
			self.assertIn(part, text)

	def test_long_names_stay_on_one_page(self):
		_result, pdf = _render(lines=("Tên máy rất dài " * 40, "01/11/2026 08:05", "3 gói"))
		self.assertEqual(len(PdfReader(io.BytesIO(pdf)).pages), 1)

	def test_text_is_escaped(self):
		html = label_pdf.render_html("ME-261101-02", "<b>x</b>", ["<script>"])
		self.assertNotIn("<script>", html)
		self.assertNotIn("<b>x</b>", html)
