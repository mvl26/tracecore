from datetime import date, datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import gs1
from tracecore.tests.utils import bru

GIAI = "9520000BPT01000001"
GTIN = "09520000000011"
CYCLE_ID = "CY-261020-0001"
PACKED = date(2026, 10, 20)
EXPIRY = date(2026, 11, 19)
CYCLE_DIGITS = "0109520000000011112610201726111921CY-261020-0001"
CYCLE_PAYLOAD = "\x1d" + CYCLE_DIGITS
CYCLE_HRI = "(01)09520000000011(11)261020(17)261119(21)CY-261020-0001"


def pack_raw(packed="261020", expiry="261119", gtin=GTIN, serial=CYCLE_ID):
	"""Chuỗi quét dạng liền (01)(11)(17)(21), cho phép làm hỏng từng phần."""
	return f"01{gtin}11{packed}17{expiry}21{serial}"


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


class TestGtin(FrappeTestCase):
	def test_gtin_check_digit(self):
		self.assertEqual(gs1.gtin_check_digit("0001234560001"), "2")
		self.assertEqual(gs1.gtin_check_digit("0952000000001"), "1")
		self.assertEqual(gs1.gtin_check_digit("0000000000000"), "0")
		# tổng có trọng số = 20 → chữ số kiểm tra 0 (không phải 10)
		self.assertEqual(gs1.gtin_check_digit("0000000000055"), "0")

	def test_gtin_check_digit_rejects_bad_body(self):
		for body in ["", "123456789012", "12345678901234", "000123456000A", "000123456000 ", None]:
			with self.assertRaises(gs1.GS1Error, msg=repr(body)) as ctx:
				gs1.gtin_check_digit(body)
			self.assertEqual(ctx.exception.code, "GS1_GTIN", msg=repr(body))

	def test_is_valid_gtin14(self):
		self.assertTrue(gs1.is_valid_gtin14("09520000000011"))
		self.assertTrue(gs1.is_valid_gtin14("00012345600012"))
		fullwidth = "".join(chr(0xFF10 + int(digit)) for digit in GTIN)  # chữ số Unicode, không phải ASCII
		for value in [
			"09520000000012",  # sai chữ số kiểm tra
			"0952000000001",  # 13 chữ số
			"0952000000001A",  # có chữ cái
			"095200000000111",  # 15 chữ số
			" 09520000000011",  # khoảng trắng đầu
			fullwidth,
			"",
			None,
			9520000000011,
		]:
			self.assertFalse(gs1.is_valid_gtin14(value), msg=repr(value))

	def test_make_test_gtin14(self):
		self.assertEqual(gs1.make_test_gtin14(1), "09520000000011")
		self.assertEqual(gs1.make_test_gtin14(99999), "0952000099999" + gs1.gtin_check_digit("0952000099999"))
		for serial in (1, 2, 37, 500, 99999):
			gtin = gs1.make_test_gtin14(serial)
			self.assertEqual(len(gtin), 14)
			self.assertTrue(gs1.is_valid_gtin14(gtin), msg=gtin)
			self.assertTrue(gs1.is_test_gtin(gtin), msg=gtin)

	def test_make_test_gtin14_ignores_site_prefix(self):
		# GTIN test luôn dùng prefix demo 952, không theo tiền tố thật của bệnh viện (D6)
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "8930000"}):
			self.assertEqual(gs1.make_test_gtin14(1), "09520000000011")

	def test_make_test_gtin14_rejects_serial_out_of_range(self):
		for serial in (0, -1, 100000, 10**9, True, 1.5, "1", None):
			with self.assertRaises(gs1.GS1Error, msg=repr(serial)) as ctx:
				gs1.make_test_gtin14(serial)
			self.assertEqual(ctx.exception.code, "GS1_ITEM_REF", msg=repr(serial))

	def test_is_test_gtin(self):
		self.assertTrue(gs1.is_test_gtin("09520000000011"))
		self.assertFalse(gs1.is_test_gtin("08930000000000"))
		self.assertFalse(gs1.is_test_gtin(""))
		self.assertFalse(gs1.is_test_gtin(None))


class TestCyclePayload(FrappeTestCase):
	@bru("BRU-ID-002")
	def test_make_cycle_payload(self):
		self.assertEqual(gs1.make_cycle_payload(GTIN, PACKED, EXPIRY, CYCLE_ID), CYCLE_PAYLOAD)
		self.assertEqual(gs1.cycle_hri(GTIN, PACKED, EXPIRY, CYCLE_ID), CYCLE_HRI)

	def test_make_cycle_payload_boundaries(self):
		# Cycle ID offline dài 18 ký tự; hạn dùng trùng ngày đóng gói vẫn hợp lệ
		payload = gs1.make_cycle_payload(GTIN, PACKED, PACKED, "CY-261020-T04-0001")
		self.assertEqual(payload, "\x1d01" + GTIN + "11261020" + "17261020" + "21CY-261020-T04-0001")
		# (21) dài đúng 20 ký tự là giới hạn trên
		self.assertTrue(gs1.make_cycle_payload(GTIN, PACKED, EXPIRY, "S" * 20).endswith("21" + "S" * 20))
		# năm 2000 và 2099 là biên của YY
		self.assertIn(
			"11000101", gs1.make_cycle_payload(GTIN, date(2000, 1, 1), date(2099, 12, 31), CYCLE_ID)
		)
		self.assertIn(
			"17991231", gs1.make_cycle_payload(GTIN, date(2000, 1, 1), date(2099, 12, 31), CYCLE_ID)
		)

	def test_make_cycle_payload_accepts_datetime(self):
		payload = gs1.make_cycle_payload(
			GTIN, datetime(2026, 10, 20, 8, 30), datetime(2026, 11, 19, 8, 30), CYCLE_ID
		)
		self.assertEqual(payload, CYCLE_PAYLOAD)

	def test_cycle_payload_rejects(self):
		cases = [
			((GTIN[:-1] + "2", PACKED, EXPIRY, CYCLE_ID), "GS1_GTIN"),  # sai check digit
			(("0952000000001", PACKED, EXPIRY, CYCLE_ID), "GS1_GTIN"),  # 13 chữ số
			((None, PACKED, EXPIRY, CYCLE_ID), "GS1_GTIN"),
			((GTIN, PACKED, EXPIRY, "CY 261020-0001"), "GS1_SERIAL"),  # khoảng trắng
			((GTIN, PACKED, EXPIRY, "C" * 21), "GS1_SERIAL"),  # dài > 20
			((GTIN, PACKED, EXPIRY, ""), "GS1_SERIAL"),
			((GTIN, PACKED, EXPIRY, "CY\x1d261020"), "GS1_SERIAL"),  # GS không thuộc CSET 82
			((GTIN, PACKED, EXPIRY, "CY-26#020-0001"), "GS1_SERIAL"),  # '#' ngoài CSET 82
			((GTIN, PACKED, EXPIRY, None), "GS1_SERIAL"),
			((GTIN, EXPIRY, PACKED, CYCLE_ID), "GS1_DATES"),  # hạn < ngày đóng gói
			((GTIN, "2026-10-20", EXPIRY, CYCLE_ID), "GS1_DATES"),  # không phải date
			((GTIN, PACKED, None, CYCLE_ID), "GS1_DATES"),
			((GTIN, date(1999, 12, 31), EXPIRY, CYCLE_ID), "GS1_DATES"),  # ngoài 2000..2099
			((GTIN, PACKED, date(2100, 1, 1), CYCLE_ID), "GS1_DATES"),
		]
		for args, code in cases:
			for fn in (gs1.make_cycle_payload, gs1.cycle_hri):
				with self.assertRaises(gs1.GS1Error, msg=(fn.__name__, args)) as ctx:
					fn(*args)
				self.assertEqual(ctx.exception.code, code, msg=(fn.__name__, args))

	def test_cycle_payload_datamatrix_roundtrip(self):
		decoded = gs1.decode_datamatrix_png(gs1.encode_datamatrix_png(CYCLE_PAYLOAD))
		self.assertEqual(decoded, CYCLE_PAYLOAD)
		result = gs1.parse_scan("]d2" + decoded)
		self.assertEqual(result["type"], "pack")
		self.assertEqual(result["id"], CYCLE_ID)


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

	def test_parse_scan_internal_codes_with_aim_prefix_and_noise(self):
		# máy quét HID đọc QR: tiền tố AIM ]Q1, CR LF, Tab, khoảng trắng, GS thừa (Review Focus 2)
		cases = {
			" ]Q1TB-0001\r\n": ("equipment", "TB-0001"),
			"]d1NV-00012\t": ("employee", "NV-00012"),
			"\x1dKE-0001": ("location", "KE-0001"),
			"]Q1TR-004\n": ("station", "TR-004"),
			"\t]Q1CN-00001\r": ("roll", "CN-00001"),
			"]Q1KE-0001\x1d": ("location", "KE-0001"),
			"\x1d]Q1TB-0001": ("equipment", "TB-0001"),
		}
		for raw, (kind, code) in cases.items():
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual((result["type"], result["id"]), (kind, code), msg=repr(raw))
		for raw in [" ]Q1TB-001\r\n", "]Q1XX-0001", "]Q1", "TB 0001", "]Q1TB-0001X"]:
			self.assertEqual(gs1.parse_scan(raw, company_prefix="9520000")["type"], "unknown", msg=repr(raw))

	@bru("BRU-ID-006")
	def test_parse_scan_unknown(self):
		for raw in ["ABC", "", "8004", "8004 X", "X" * 200, "(01)09520000000013", "TR-04", "NV-1"]:
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(result["type"], "unknown", msg=repr(raw))
			self.assertIsNone(result["id"])

	def test_parse_scan_truncates_raw(self):
		self.assertEqual(len(gs1.parse_scan("A" * 500)["raw"]), gs1.MAX_SCAN_LENGTH)

	def test_parse_scan_default_prefix_from_config(self):
		self.assertEqual(gs1.parse_scan(GIAI)["type"], "set")

	def test_clean_scan(self):
		self.assertEqual(gs1.clean_scan("]d2\x1d" + GIAI + "\r\n"), GIAI)
		self.assertEqual(gs1.clean_scan("  " + CYCLE_PAYLOAD + "\x1d\t"), CYCLE_DIGITS)
		self.assertEqual(gs1.clean_scan(None), "")

	def test_parse_scan_pack_variants(self):
		variants = [
			"]d2\x1d0109520000000011112610201726111921CY-261020-0001\r\n",  # AIM + FNC1 + CR LF
			"]d2" + CYCLE_DIGITS,  # AIM, không FNC1
			CYCLE_PAYLOAD,  # FNC1 đầu
			CYCLE_PAYLOAD + "\x1d",  # GS thừa cuối
			"  " + CYCLE_HRI + "\t",  # chuỗi người đọc
			"]d2" + CYCLE_HRI,
			CYCLE_DIGITS,  # dạng liền, máy quét không truyền FNC1
		]
		for raw in variants:
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(result["type"], "pack", msg=repr(raw))
			self.assertEqual(result["id"], CYCLE_ID, msg=repr(raw))
			self.assertEqual(result["gtin"], GTIN, msg=repr(raw))
			self.assertEqual(result["packed"], PACKED, msg=repr(raw))
			self.assertEqual(result["expiry"], EXPIRY, msg=repr(raw))
			self.assertEqual(result["raw"], gs1.clean_scan(raw), msg=repr(raw))
		for raw in ["CY-261020-0001", "CY-261020-T04-0001"]:
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(result["type"], "pack", msg=raw)
			self.assertEqual(result["id"], raw)
			self.assertNotIn("gtin", result)

	def test_parse_scan_pack_edge_values(self):
		result = gs1.parse_scan("(01)" + GTIN + "(11)261020(17)261119(21)CY-261020-T04-0001")
		self.assertEqual((result["type"], result["id"]), ("pack", "CY-261020-T04-0001"))
		# (21) dài đúng 20 ký tự và hạn dùng trùng ngày đóng gói vẫn hợp lệ
		result = gs1.parse_scan(pack_raw(expiry="261020", serial="S" * 20))
		self.assertEqual((result["type"], result["id"]), ("pack", "S" * 20))
		self.assertEqual(result["expiry"], result["packed"])
		# năm nhuận 2028 có 29/02
		result = gs1.parse_scan(pack_raw(packed="280229", expiry="280301"))
		self.assertEqual(result["packed"], date(2028, 2, 29))

	@bru("BRU-ID-006")
	def test_parse_scan_pack_bad_check_digit(self):
		bad_gtin = "09520000000012"
		for raw in [
			"(01)" + bad_gtin + "(11)261020(17)261119(21)CY-261020-0001",
			pack_raw(gtin=bad_gtin),
			"\x1d" + pack_raw(gtin=bad_gtin),
		]:
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(result["type"], "unknown", msg=repr(raw))
			self.assertIsNone(result["id"])

	def test_parse_scan_pack_rejects_malformed(self):
		bad = [
			pack_raw(packed="261320"),  # tháng đóng gói 13
			pack_raw(expiry="261340"),  # tháng 13, ngày 40
			pack_raw(expiry="260230"),  # 30/02 hạn dùng
			pack_raw(packed="260230"),  # 30/02 ngày đóng gói
			pack_raw(packed="270229", expiry="270301"),  # 29/02/2027 (không nhuận)
			pack_raw(packed="261000"),  # ngày 00
			pack_raw(packed="26102A"),  # ký tự không phải số trong ngày
			pack_raw(packed="261119", expiry="261019"),  # hạn dùng < ngày đóng gói
			pack_raw(serial=""),  # thiếu giá trị (21)
			pack_raw(serial="CY 261020-0001"),  # khoảng trắng trong serial
			pack_raw(serial="CY#261020-0001"),  # ký tự ngoài CSET 82
			pack_raw(serial="C" * 21),  # serial dài > 20
			CYCLE_PAYLOAD + "\x1d10LOT123",  # còn AI khác sau (21): không phải nhãn của ta
			CYCLE_HRI + "\x1d10LOT123",
			f"01{GTIN}17261119" + "11261020" + "21" + CYCLE_ID,  # sai thứ tự AI (17 trước 11)
			f"01{GTIN}11261020" + "21" + CYCLE_ID,  # thiếu (17)
			f"01{GTIN}17261119" + "21" + CYCLE_ID,  # thiếu (11)
			"(01)" + GTIN + "(11)261020(17)261119(21)",  # HRI thiếu serial
			"(01)" + GTIN + "(17)261119(11)261020(21)" + CYCLE_ID,  # HRI sai thứ tự
			"(01)" + GTIN + "(11)261020" + "17261119" + "(21)" + CYCLE_ID,  # trộn HRI và dạng liền
			"(01)0952000000001(11)261020(17)261119(21)" + CYCLE_ID,  # GTIN 13 chữ số
			"0109520000000011112610201726111921CY-261020-0001" + "\r\nX",  # nội dung thừa sau xuống dòng
		]
		for raw in bad:
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(result["type"], "unknown", msg=repr(raw))
			self.assertIsNone(result["id"], msg=repr(raw))
			self.assertNotIn("gtin", result, msg=repr(raw))

	def test_parse_scan_pack_does_not_shadow_giai(self):
		# Set ID GIAI vẫn nhận dạng như cũ khi có nhánh gói GS1 chạy trước
		self.assertEqual(gs1.parse_scan("(8004)" + GIAI)["type"], "set")
		self.assertEqual(gs1.parse_scan("]d2\x1d8004" + GIAI)["id"], GIAI)
		self.assertEqual(gs1.parse_scan(GIAI, company_prefix="9520000")["type"], "set")
		# GIAI bắt đầu bằng "01" nhưng không đúng cấu trúc (01)(11)(17)(21) vẫn là Set ID
		giai = "0109520000000011ABCDEFGH"
		result = gs1.parse_scan(giai, company_prefix="0109")
		self.assertEqual((result["type"], result["id"]), ("set", giai))


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

	def test_zpl_datamatrix_cycle(self):
		zpl = gs1.zpl_datamatrix(gs1.make_cycle_payload(GTIN, PACKED, EXPIRY, CYCLE_ID), 0, 0)
		self.assertIn("^FD_10109520000000011112610201726111921CY-261020-0001^FS", zpl)


INSTRUMENT_GIAI = "9520000I-00000001"


class TestInstrumentGiai(FrappeTestCase):
	"""Mã GIAI khắc laser của dụng cụ (FEAT-014 Task 5, A-06 I8): ``<prefix>I-<8 số>``."""

	def test_make_instrument_giai(self):
		self.assertEqual(gs1.INSTRUMENT_ASSET_PREFIX, "I-")
		self.assertEqual(gs1.INSTRUMENT_SERIAL_DIGITS, 8)
		self.assertEqual(gs1.make_instrument_giai("9520000", 1), INSTRUMENT_GIAI)
		self.assertEqual(gs1.make_instrument_giai("893123456789", 99999999), "893123456789I-99999999")
		for serial in (0, -1, 100000000, True, "1", 1.0, None):
			with self.assertRaises(gs1.GS1Error, msg=repr(serial)):
				gs1.make_instrument_giai("9520000", serial)
		for prefix in ("", "952", "95200001234567", "952A000"):
			with self.assertRaises(gs1.GS1Error, msg=repr(prefix)):
				gs1.make_instrument_giai(prefix, 1)

	def test_is_demo_prefix(self):
		for prefix in ("9520000", "952", "9521234"):
			self.assertTrue(gs1.is_demo_prefix(prefix), msg=prefix)
		for prefix in ("8930000", "0952000", "", None):
			self.assertFalse(gs1.is_demo_prefix(prefix), msg=repr(prefix))

	def test_instrument_giai_never_parses_as_set(self):
		variants = [
			INSTRUMENT_GIAI,  # gõ/quét mã trần
			"  " + INSTRUMENT_GIAI + "\r\n",
			"(8004)" + INSTRUMENT_GIAI,  # chuỗi người đọc
			"8004" + INSTRUMENT_GIAI,  # máy quét không truyền FNC1
			"\x1d8004" + INSTRUMENT_GIAI,  # FNC1 dạng GS
			"]d2\x1d8004" + INSTRUMENT_GIAI + "\x1d",  # AIM GS1 DataMatrix + GS thừa
			"]d28004" + INSTRUMENT_GIAI,
		]
		for raw in variants:
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual(
				result, {"type": "instrument", "id": INSTRUMENT_GIAI, "raw": result["raw"]}, msg=repr(raw)
			)
		# có AI (8004) thì nhận theo dạng, không phụ thuộc tiền tố cấu hình
		self.assertEqual(
			gs1.parse_scan("(8004)8930000I-00000042", company_prefix="9520000")["type"], "instrument"
		)
		# không AI: phần sau tiền tố cấu hình phải đúng I-<8 số>
		self.assertEqual(gs1.parse_scan("8930000I-00000042", company_prefix="9520000")["type"], "unknown")
		self.assertEqual(gs1.parse_scan("8930000I-00000042", company_prefix="8930000")["type"], "instrument")
		for raw in ("9520000I-0000001", "9520000I-000000001", "9520000I00000001", "9520000i-00000001"):
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertNotEqual(result["type"], "instrument", msg=raw)

	def test_legacy_codes_keep_their_parse_result(self):
		# loại mã cũ không đổi kết quả khi có nhánh mã dụng cụ (A-06 I8)
		cases = {
			GIAI: ("set", GIAI),
			"(8004)" + GIAI: ("set", GIAI),
			"]d2\x1d8004" + GIAI: ("set", GIAI),
			"9520000T4000100000001": ("set", "9520000T4000100000001"),
			"9520000I1000001": ("set", "9520000I1000001"),  # loại bộ mã "I1"
			"(8004)9520000II000001": ("set", "9520000II000001"),
			CYCLE_HRI: ("pack", CYCLE_ID),
			CYCLE_PAYLOAD: ("pack", CYCLE_ID),
			"CY-261019-0001": ("pack", "CY-261019-0001"),
			"NV-00012": ("employee", "NV-00012"),
			"TB-0003": ("equipment", "TB-0003"),
			"KE-0001": ("location", "KE-0001"),
			"TR-004": ("station", "TR-004"),
			"CN-00001": ("roll", "CN-00001"),
			"CT-261019-00001": ("container", "CT-261019-00001"),
			"ABC": ("unknown", None),
		}
		for raw, expected in cases.items():
			result = gs1.parse_scan(raw, company_prefix="9520000")
			self.assertEqual((result["type"], result["id"]), expected, msg=repr(raw))

	def test_instrument_giai_datamatrix_roundtrip(self):
		png = gs1.encode_datamatrix_png(gs1.giai_payload(INSTRUMENT_GIAI))
		self.assertEqual(gs1.decode_datamatrix_png(png), "\x1d8004" + INSTRUMENT_GIAI)
		self.assertEqual(gs1.parse_scan(gs1.decode_datamatrix_png(png))["type"], "instrument")


class TestBomCode(FrappeTestCase):
	"""Mã phiên bản BOM trên phiếu kiểm đếm (FEAT-015 S8): ``BOM-<TYPE_CODE>-V<n>``, không phải GS1."""

	def test_make_bom_code_and_parse_scan(self):
		self.assertEqual(gs1.BOM_CODE_PREFIX, "BOM-")
		self.assertEqual(gs1.make_bom_code("KHAM01", 3), "BOM-KHAM01-V3")
		self.assertEqual(gs1.make_bom_code("AB", 9999), "BOM-AB-V9999")
		self.assertEqual(gs1.make_bom_code("ABCDEFGH", 1), "BOM-ABCDEFGH-V1")
		for bad in (
			("X", 1),
			("ABCDEFGHI", 1),
			("kham01", 1),
			("KH-1", 1),
			("", 1),
			(None, 1),
			("KHAM01", 0),
			("KHAM01", -1),
			("KHAM01", 10000),
			("KHAM01", True),
			("KHAM01", "3"),
			("KHAM01", 3.0),
		):
			with self.subTest(bad=bad), self.assertRaises(ValueError):
				gs1.make_bom_code(*bad)

		expected = {
			"type": "bom",
			"id": "BOM-KHAM01-V3",
			"set_type": "KHAM01",
			"bom_version": 3,
			"raw": "BOM-KHAM01-V3",
		}
		for raw in (
			"BOM-KHAM01-V3",
			"]d1BOM-KHAM01-V3",
			"  BOM-KHAM01-V3\r\n",
			"\x1d]d2BOM-KHAM01-V3\t",
			"]Q1BOM-KHAM01-V3",
		):
			with self.subTest(raw=raw):
				self.assertEqual(gs1.parse_scan(raw), expected)
				self.assertEqual(gs1.parse_scan(raw, company_prefix="9520000"), expected)
		self.assertEqual(gs1.parse_scan("BOM-AB-V9999")["bom_version"], 9999)
		for bad in (
			"BOM-X-V1",
			"BOM-KHAM01-V0",
			"BOM-KHAM01-V03",
			"BOM-KHAM01-V10000",
			"BOM-kham01-V3",
			"BOM-KHAM01-3",
			"BOM-KHAM01-V3X",
			"XBOM-KHAM01-V3",
			"BOM-ABCDEFGHI-V1",
			"BOM--V1",
		):
			with self.subTest(bad=bad):
				self.assertEqual(gs1.parse_scan(bad)["type"], "unknown")

		# loại mã cũ không đổi kết quả khi có nhánh mã BOM
		cases = {
			GIAI: ("set", GIAI),
			"(8004)" + GIAI: ("set", GIAI),
			CYCLE_HRI: ("pack", CYCLE_ID),
			CYCLE_PAYLOAD: ("pack", CYCLE_ID),
			"CY-261019-0001": ("pack", "CY-261019-0001"),
			"NV-00012": ("employee", "NV-00012"),
			"TB-0003": ("equipment", "TB-0003"),
			"KE-0001": ("location", "KE-0001"),
			"TR-004": ("station", "TR-004"),
			"CN-00001": ("roll", "CN-00001"),
			"CT-261019-00001": ("container", "CT-261019-00001"),
			INSTRUMENT_GIAI: ("instrument", INSTRUMENT_GIAI),
			"(8004)" + INSTRUMENT_GIAI: ("instrument", INSTRUMENT_GIAI),
			"ABC": ("unknown", None),
		}
		for raw, kind in cases.items():
			with self.subTest(raw=raw):
				result = gs1.parse_scan(raw, company_prefix="9520000")
				self.assertEqual((result["type"], result["id"]), kind)

	def test_bom_code_datamatrix_roundtrip(self):
		code = gs1.make_bom_code("KHAM01", 12)
		decoded = gs1.decode_datamatrix_png(gs1.encode_datamatrix_png(code))
		self.assertEqual(decoded, "BOM-KHAM01-V12")
		self.assertEqual(gs1.parse_scan(decoded)["type"], "bom")
