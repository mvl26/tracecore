import io

import pyqrcode
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tracecore.core import gs1, qr

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class TestQrPng(FrappeTestCase):
	def test_qr_png_encodes_payload(self):
		for payload in ["TB-0001", "NV-00012", "CN-00001", "KE-0001", "TR-004", "HOSP card 0001"]:
			png = qr.qr_png(payload)
			self.assertTrue(png.startswith(PNG_MAGIC), msg=payload)
			expected = pyqrcode.create(payload, error=qr.ERROR_LEVEL).code
			size = len(expected) * 8 + 2 * 16
			self.assertEqual(Image.open(io.BytesIO(png)).size, (size, size), msg=payload)
			self.assertEqual(qr.png_matrix(png), expected, msg=payload)
			self.assertEqual(qr.decode_png(png), payload, msg=payload)

	def test_qr_png_module_and_margin(self):
		png = qr.qr_png("TB-0001", module_px=3, margin_px=5)
		n = len(qr.matrix("TB-0001"))
		self.assertEqual(Image.open(io.BytesIO(png)).size, (n * 3 + 10, n * 3 + 10))
		self.assertEqual(qr.decode_png(png), "TB-0001")

	def test_qr_png_larger_version_roundtrip(self):
		payload = "TB-0001-" + "X" * 60  # version > 1, nhiều khối, có mẫu căn chỉnh
		png = qr.qr_png(payload)
		self.assertGreater(len(qr.matrix(payload)), 25)
		self.assertEqual(qr.decode_png(png), payload)

	def test_qr_png_rejects_bad_input(self):
		for payload in ["", None]:
			with self.assertRaises(qr.QRError, msg=repr(payload)):
				qr.qr_png(payload)
		with self.assertRaises(qr.QRError):
			qr.qr_png("TB-0001", module_px=0)
		with self.assertRaises(qr.QRError):
			qr.qr_png("TB-0001", margin_px=-1)

	def test_decode_png_rejects_non_qr(self):
		blank = io.BytesIO()
		Image.new("L", (40, 40), 255).save(blank, format="PNG")
		with self.assertRaises(qr.QRError):
			qr.decode_png(blank.getvalue())
		with self.assertRaises(qr.QRError):
			qr.decode_png(gs1.encode_datamatrix_png("TB-0001"))


class TestZplQr(FrappeTestCase):
	def test_zpl_qr_format(self):
		zpl = qr.zpl_qr("TB-0001", 30, 40)
		self.assertEqual(zpl, f"^FO30,40^BQN,2,6^FD{qr.ERROR_LEVEL}A,TB-0001^FS")
		self.assertIn("^BQN,2,6^FDMA,TB-0001^FS", zpl)
		self.assertIn("^BQN,2,4^", qr.zpl_qr("TB-0001", 0, 0, magnification=4))

	def test_zpl_qr_rejects_control_chars(self):
		for payload in ["TB^0001", "TB~0001", "^XZ", "", None]:
			with self.assertRaises(qr.QRError, msg=repr(payload)):
				qr.zpl_qr(payload, 0, 0)
		for magnification in [0, 11]:
			with self.assertRaises(qr.QRError):
				qr.zpl_qr("TB-0001", 0, 0, magnification=magnification)

	def test_zpl_qr_rejects_bad_coordinates(self):
		# x, y có thể đến từ dữ liệu request/mẫu: chỉ nhận số nguyên không âm, không để chèn lệnh ZPL
		for bad in [-1, True, False, 1.5, "10", "0^XZ", None]:
			with self.assertRaises(qr.QRError, msg=f"x={bad!r}"):
				qr.zpl_qr("TB-0001", bad, 0)
			with self.assertRaises(qr.QRError, msg=f"y={bad!r}"):
				qr.zpl_qr("TB-0001", 0, bad)
		self.assertTrue(qr.zpl_qr("TB-0001", 0, 0).startswith("^FO0,0^BQN"))

	def test_zpl_qr_payload_is_printable_ascii(self):
		# mã đối tượng là ASCII; chữ có dấu, xuống dòng hay ký tự điều khiển không được vào ^FD của QR
		for payload in ["TB-0001é", "Máy", "TB\n0001", "TB\r0001", "TB\x000001", "TB\x1d0001", "TB\x7f"]:
			with self.assertRaises(qr.QRError, msg=repr(payload)):
				qr.zpl_qr(payload, 0, 0)
		self.assertIn("^FDMA,CARD 12/34^FS", qr.zpl_qr("CARD 12/34", 0, 0))
