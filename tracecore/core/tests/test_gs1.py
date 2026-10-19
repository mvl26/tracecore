from frappe.tests.utils import FrappeTestCase

from tracecore.core import gs1
from tracecore.tests.utils import bru

GIAI = "9520000BPT01000001"


class TestMakeGiai(FrappeTestCase):
	def test_make_giai_valid(self):
		self.assertEqual(gs1.make_giai("9520000", "BPT01000001"), GIAI)
		self.assertEqual(gs1.giai_hri(GIAI), "(8004)" + GIAI)
		self.assertEqual(gs1.giai_payload(GIAI), "\x1d8004" + GIAI)

	@bru("BRU-ID-001")
	def test_make_giai_rejects(self):
		bad = [
			("95A0000", "X1"),  # prefix không phải số
			("952", "X1"),  # prefix < 4 chữ số
			("9520000000000", "X1"),  # prefix > 12 chữ số
			("9520000", "BPT#1"),  # ký tự ngoài CSET 82
			("9520000", "BPT 1"),  # khoảng trắng
			("9520000", ""),  # asset_ref rỗng
			("9520000", "A" * 24),  # tổng 31 ký tự > 30
		]
		for prefix, ref in bad:
			with self.assertRaises(gs1.GS1Error, msg=(prefix, ref)):
				gs1.make_giai(prefix, ref)

	def test_make_giai_max_length(self):
		self.assertEqual(len(gs1.make_giai("9520000", "A" * 23)), 30)


class TestParseScan(FrappeTestCase):
	def test_parse_scan_variants(self):
		variants = [
			"]d2\x1d8004" + GIAI + "\r\n",  # AIM GS1 DataMatrix + FNC1 dạng GS
			"(8004)" + GIAI,  # chuỗi người đọc
			"8004" + GIAI,  # máy quét không truyền FNC1
			"8004" + GIAI + "\x1d",  # GS thừa cuối
			"  " + GIAI + "\t",  # gõ tay Set ID trần
		]
		for raw in variants:
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(result["type"], "set", msg=repr(raw))
			self.assertEqual(result["id"], GIAI, msg=repr(raw))

	def test_parse_scan_internal_codes(self):
		cases = {
			"NV-00012": "employee",
			"TB-0003": "equipment",
			"KE-0001": "location",
			"TR-004": "station",
			"CN-00001": "roll",
			"CT-261019-00001": "container",
			"CY-261019-0001": "pack",
			"CY-261019-T04-0001": "pack",
		}
		for raw, kind in cases.items():
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(result["type"], kind, msg=raw)
			self.assertEqual(result["id"], raw)
		self.assertEqual(gs1.parse_scan("]Q3TR-004\r")["id"], "TR-004")

	@bru("BRU-ID-006")
	def test_parse_scan_unknown(self):
		for raw in ["ABC", "", "8004", "8004 X", "X" * 200, "(01)09520000000013", "TR-04", "NV-1"]:
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(result["type"], "unknown", msg=repr(raw))
			self.assertIsNone(result["id"])

	def test_parse_scan_default_prefix_from_config(self):
		self.assertEqual(gs1.parse_scan(GIAI)["type"], "set")


class TestEncoders(FrappeTestCase):
	def test_datamatrix_png_roundtrip(self):
		png = gs1.encode_datamatrix_png(gs1.giai_payload(GIAI))
		self.assertTrue(png.startswith(b"\x89PNG"))
		self.assertEqual(gs1.decode_datamatrix_png(png), "\x1d8004" + GIAI)

	def test_zpl_datamatrix(self):
		zpl = gs1.zpl_datamatrix(gs1.giai_payload(GIAI), 30, 40)
		self.assertTrue(zpl.startswith("^FO30,40^BXN,6,200,0,0,1,_,1"))
		self.assertIn("^FD_18004" + GIAI + "^FS", zpl)
		self.assertIn("^FDA__B^FS", gs1.zpl_datamatrix("A_B", 0, 0))
