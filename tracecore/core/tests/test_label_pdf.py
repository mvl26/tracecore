"""PDF nhãn mã mẻ/lô (A-99): PDF thật từ wkhtmltopdf, QR trong PDF quét ra đúng mã."""

import base64
import io
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase
from pypdf import PdfReader

from tracecore.core import gs1, label_pdf, qr
from tracecore.core.errors import BlockedError

PAYLOAD = "01095200000000031126110117271101\x1d21CY-261101-0001"
ROWS = [
	("CY-261101-0001", "code"),
	("(01)09520000000003 (11)261101", ""),
	("SET-0001", "mono"),
	("Bộ phẫu thuật", "title"),
	("EXPIRY DATE / EXP: 01/11/2027", "title"),
]


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


class TestPackLabelPdf(FrappeTestCase):
	"""A-101: nhãn gói T4 ra PDF có DataMatrix GS1 thật và đủ chữ của bản xem trước."""

	def test_datamatrix_in_the_pdf_decodes_back_to_the_payload(self):
		pdf = label_pdf.pack_pdf("CY-261101-0001", PAYLOAD, ROWS)
		reader = PdfReader(io.BytesIO(pdf))
		self.assertEqual(len(reader.pages), 1)
		self.assertEqual(gs1.decode_datamatrix_png(reader.pages[0].images[0].data), PAYLOAD)

	def test_every_row_is_in_the_pdf(self):
		text = (
			PdfReader(io.BytesIO(label_pdf.pack_pdf("CY-261101-0001", PAYLOAD, ROWS))).pages[0].extract_text()
		)
		for part in ("CY-261101-0001", "SET-0001", "01/11/2027"):
			self.assertIn(part, text)

	def test_long_shortage_list_is_not_cut_and_stays_on_one_page(self):
		"""Danh sách dụng cụ thiếu dài vẫn đủ: trang cao theo nội dung, không cắt chữ, không sang trang."""
		rows = [*ROWS, ("MISSING: " + ", ".join(f"Instrument {n}" for n in range(60)) + " END", "title")]
		reader = PdfReader(io.BytesIO(label_pdf.pack_pdf("CY-261101-0001", PAYLOAD, rows)))
		self.assertEqual(len(reader.pages), 1)
		self.assertIn("END", reader.pages[0].extract_text())

	def test_text_is_escaped(self):
		html = label_pdf.pack_html("CY-261101-0001", "QQ==", [("<script>", "")])
		self.assertNotIn("<script>", html)

	def test_merge_keeps_each_label_as_one_page(self):
		first = label_pdf.pack_pdf("CY-261101-0001", PAYLOAD, ROWS)
		merged = label_pdf.merge([first, first])
		self.assertEqual(len(PdfReader(io.BytesIO(merged)).pages), 2)
		self.assertIs(label_pdf.merge([first]), first)

	def assert_blocked(self, code, call):
		with self.assertRaises(BlockedError) as caught:
			call()
		self.assertEqual(caught.exception.block.code, "LABEL_PDF_FAILED")
		self.assertIn(code, caught.exception.block.reason)
		self.assertEqual(caught.exception.block.http_status, 409)

	def test_missing_pdf_tool_is_a_clear_block(self):
		with patch("frappe.utils.pdf.get_pdf", side_effect=OSError("No wkhtmltopdf executable found")):
			self.assert_blocked("CY-261101-0001", lambda: label_pdf.pack_pdf("CY-261101-0001", PAYLOAD, ROWS))
			self.assert_blocked("ME-261101-02", lambda: label_pdf.render("ME-261101-02", "t", []))

	def test_missing_datamatrix_library_is_a_clear_block(self):
		with patch.object(gs1, "encode_datamatrix_png", side_effect=ImportError("libdmtx")):
			self.assert_blocked("CY-261101-0001", lambda: label_pdf.pack_pdf("CY-261101-0001", PAYLOAD, ROWS))
