from unittest.mock import patch

import frappe
from frappe.model.naming import make_autoname
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry, gs1
from tracecore.tests.utils import bru

EXPECTED = {
	"NV": (r"NV-\d{5}", "employee", "Employee"),
	"TB": (r"TB-\d{4}", "equipment", "Equipment"),
	"KE": (r"KE-\d{4}", "location", "Sterile Location"),
	"TR": (r"TR-\d{3}", "station", "Zone Station"),
	"CN": (r"CN-\d{5}", "roll", "Item"),
}


class TestNextCode(FrappeTestCase):
	def test_code_formats_match_architecture(self):
		self.assertEqual(
			code_registry.CODE_FORMATS,
			{"NV": ("NV-", 5), "TB": ("TB-", 4), "KE": ("KE-", 4), "TR": ("TR-", 3), "CN": ("CN-", 5)},
		)

	@bru("BRU-ID-006")
	def test_next_code_formats_and_registers(self):
		for prefix, (pattern, kind, ref_doctype) in EXPECTED.items():
			code = code_registry.next_code(prefix, ref_doctype, "REF-" + prefix, station="TR-004")
			self.assertRegex(code, f"^{pattern}$")
			row = frappe.db.get_value(
				"Code Registry",
				code,
				["prefix", "ref_doctype", "ref_name", "issued_at", "status"],
				as_dict=True,
			)
			self.assertEqual(
				row,
				{
					"prefix": prefix,
					"ref_doctype": ref_doctype,
					"ref_name": "REF-" + prefix,
					"issued_at": "TR-004",
					"status": "Active",
				},
				msg=prefix,
			)
			scan = gs1.parse_scan(f" ]Q1{code}\r\n")
			self.assertEqual((scan["type"], scan["id"]), (kind, code))

	def test_next_code_without_ref(self):
		code = code_registry.next_code("KE")
		row = frappe.db.get_value("Code Registry", code, ["prefix", "ref_doctype", "ref_name"], as_dict=True)
		self.assertEqual((row.prefix, row.ref_doctype, row.ref_name), ("KE", None, None))

	@bru("BRU-ID-006")
	def test_next_code_skips_already_registered_numbers(self):
		first = code_registry.next_code("KE")
		number = int(first.split("-")[1])
		taken = f"KE-{number + 1:04d}"
		code_registry.register(taken, "KE", "Sterile Location", "manual")
		second = code_registry.next_code("KE")
		self.assertEqual(second, f"KE-{number + 2:04d}")
		# số đã bỏ qua vẫn giữ ref cũ, không bị ghi đè
		self.assertEqual(frappe.db.get_value("Code Registry", taken, "ref_name"), "manual")

	def test_next_code_unknown_prefix_rejected(self):
		for prefix in ["XX", "CY", "CT", "nv", "", None, "TB-"]:
			with self.assertRaises(frappe.ValidationError, msg=repr(prefix)):
				code_registry.next_code(prefix)

	def test_next_code_series_exhausted_rejected(self):
		with patch.object(code_registry, "getseries", return_value="1000"):
			with self.assertRaises(frappe.ValidationError):
				code_registry.next_code("TR")
		self.assertFalse(code_registry.is_issued("TR-1000"))

	@bru("BRU-ID-006")
	def test_next_code_is_unique_under_repeated_calls(self):
		codes = [code_registry.next_code("CN", "Item", "Label roll item") for _ in range(200)]
		self.assertEqual(len(set(codes)), 200)
		numbers = [int(code.split("-")[1]) for code in codes]
		self.assertEqual(numbers, list(range(numbers[0], numbers[0] + 200)))
		self.assertTrue(all(code_registry.is_issued(code) for code in codes))

	@bru("BRU-ID-006")
	def test_next_code_shares_series_with_doctype_naming_and_rollback_does_not_burn(self):
		# next_code("TB") và naming series `TB-.####` của Equipment dùng chung một bộ đếm
		first = code_registry.next_code("TB")
		number = int(first.split("-")[1])
		self.assertEqual(make_autoname("TB-.####"), f"TB-{number + 1:04d}")
		self.assertEqual(code_registry.next_code("TB"), f"TB-{number + 2:04d}")
		# số cấp trong một savepoint bị hoàn tác thì bộ đếm cũng lùi: không thủng số
		frappe.db.savepoint("tc_code_burn")
		burned = code_registry.next_code("TB")
		self.assertEqual(burned, f"TB-{number + 3:04d}")
		frappe.db.rollback(save_point="tc_code_burn")
		self.assertFalse(code_registry.is_issued(burned))
		self.assertEqual(code_registry.next_code("TB"), burned)
		self.assertEqual(make_autoname("TB-.####"), f"TB-{number + 4:04d}")


class TestRegisterCard(FrappeTestCase):
	@bru("BRU-ID-006")
	def test_register_card_rules(self):
		code = code_registry.register_card("  ]Q1BV0012345\r\n", "Employee", "EMP-0001")
		self.assertEqual(code, "BV0012345")
		row = frappe.db.get_value(
			"Code Registry", code, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
		)
		self.assertEqual(
			row, {"prefix": "CARD", "ref_doctype": "Employee", "ref_name": "EMP-0001", "status": "Active"}
		)
		# trùng mã đã đăng ký → chặn (FR-M9-07.4)
		with self.assertRaises(code_registry.CodeAlreadyIssuedError):
			code_registry.register_card("BV0012345", "Employee", "EMP-0002")
		# trùng một mã hệ thống đã cấp cũng là trùng
		issued = code_registry.next_code("NV", "Employee", "EMP-0003")
		with self.assertRaises(frappe.ValidationError):
			code_registry.register_card(issued, "Employee", "EMP-0004")

		giai = gs1.make_giai(code_registry.company_prefix(), "CRD000001")
		rejected = [
			"NV-12345",  # tiền tố hệ thống
			"nv-12345",  # tiền tố hệ thống, chữ thường
			"TB-X1",
			"KE-ABCD",
			"TR-0001",
			"CN-9",
			"CT-261019-00001",
			"CY-261019-0001",
			"LR-0001",
			"ME-0001",
			giai,  # chuỗi GIAI của Set ID
			"(8004)" + giai,
			"BV 0012",  # khoảng trắng giữa
			"BV#0012",  # ngoài CSET 82
			"BVĐ0012",  # ký tự có dấu
			"BV1",  # < 4 ký tự
			"B" * 41,  # > 40 ký tự
			"",
			None,
		]
		for raw in rejected:
			with self.assertRaises(frappe.ValidationError, msg=repr(raw)):
				code_registry.register_card(raw, "Employee", "EMP-0005")
			if raw:
				self.assertFalse(code_registry.is_issued(gs1.clean_scan(raw)), msg=repr(raw))

	def test_register_card_length_bounds_and_scan(self):
		short = code_registry.register_card("AB12", "Employee", "EMP-0006")
		long = code_registry.register_card("C" * 40, "Employee", "EMP-0007")
		self.assertEqual((short, long), ("AB12", "C" * 40))

	def test_register_card_requires_ref(self):
		for ref_doctype, ref_name in [("", "EMP-0008"), ("Employee", ""), (None, None)]:
			with self.assertRaises(frappe.ValidationError):
				code_registry.register_card("BV7777777", ref_doctype, ref_name)
		self.assertFalse(code_registry.is_issued("BV7777777"))


class TestNextInstrumentGiai(FrappeTestCase):
	"""Mã GIAI dụng cụ (FEAT-014 Task 5, A-06 I8): series riêng, ghi sổ prefix ``GI`` ref Instrument."""

	@bru("BRU-ID-001")
	def test_next_instrument_giai_registers_and_skips_taken_numbers(self):
		self.assertEqual(code_registry.INSTRUMENT_GIAI_PREFIX, "GI")
		prefix = gs1.configured_company_prefix()
		first = code_registry.next_instrument_giai("CR-GIAI-1")
		self.assertRegex(first, rf"^{prefix}I-\d{{8}}$")
		row = frappe.db.get_value(
			"Code Registry", first, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
		)
		self.assertEqual(
			row, {"prefix": "GI", "ref_doctype": "Instrument", "ref_name": "CR-GIAI-1", "status": "Active"}
		)
		serial = int(first[-8:])
		# số kế tiếp đã có trong sổ (đăng ký tay) → bỏ qua
		taken = gs1.make_instrument_giai(prefix, serial + 1)
		code_registry.register(taken, "GI", "Instrument", "OTHER")
		second = code_registry.next_instrument_giai("CR-GIAI-2")
		self.assertEqual(second, gs1.make_instrument_giai(prefix, serial + 2))
		# series riêng: không đụng series Set ID
		set_id = code_registry.next_set_id("CRG")
		self.assertEqual(gs1.parse_scan(set_id)["type"], "set")
		self.assertEqual(gs1.parse_scan(second)["type"], "instrument")

	def test_next_instrument_giai_series_exhausted(self):
		with patch.object(code_registry, "getseries", return_value="100000000"):
			with self.assertRaises(frappe.ValidationError):
				code_registry.next_instrument_giai("CR-GIAI-X")

	def test_demo_prefix_blocked_outside_dev_or_test(self):
		from tracecore.core.errors import BlockedError

		production = {"developer_mode": 0, "allow_tests": 0, "tc_gs1_company_prefix": "9520000"}
		with patch.dict(frappe.conf, production), patch.dict(frappe.flags, {"in_test": False}):
			self.assertFalse(code_registry.demo_prefix_allowed())
			with self.assertRaises(BlockedError) as raised:
				code_registry.next_instrument_giai("CR-GIAI-P")
			self.assertEqual(raised.exception.block.code, "GS1_PREFIX_NOT_CONFIGURED")
			# chưa cấu hình tiền tố (rơi về tiền tố demo) cũng bị chặn
			with patch.dict(frappe.conf, {"tc_gs1_company_prefix": None}):
				with self.assertRaises(BlockedError):
					code_registry.next_instrument_giai("CR-GIAI-P")
			# tiền tố sai định dạng → chặn, không 500
			with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "89A"}):
				with self.assertRaises(BlockedError):
					code_registry.next_instrument_giai("CR-GIAI-P")
			# tiền tố thật → cấp được
			with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "8930001"}):
				code = code_registry.next_instrument_giai("CR-GIAI-R")
			self.assertTrue(code.startswith("8930001I-"))
		self.assertEqual(frappe.db.count("Code Registry", {"ref_name": "CR-GIAI-P"}), 0)
		self.assertTrue(code_registry.demo_prefix_allowed())


PRODUCTION_CONF = {"developer_mode": 0, "allow_tests": 0}
INSTRUMENT_BLOCK_TEXTS = (
	"GS1 prefix not configured",
	"GS1 Company Prefix {0} cannot be used for instrument codes on this site: it is the demo prefix or is not 4-12 digits.",
	"Ask the administrator to set the hospital's real GS1 Company Prefix before assigning or etching instrument codes.",
)


def production_site(**conf):
	"""Giả lập site không phải dev/test (không developer_mode, không allow_tests, không đang chạy test)."""
	return patch.dict(frappe.conf, {**PRODUCTION_CONF, **conf}), patch.dict(frappe.flags, {"in_test": False})


class TestNextSetId(FrappeTestCase):
	"""Set ID GIAI (FEAT-016 Task 1, G2, G3): cấu trúc, không check digit, hết dải, chặn tiền tố demo."""

	def series_key(self, type_code):
		return f"{code_registry.company_prefix()}{type_code}"

	def set_series(self, key, current):
		frappe.db.sql(
			"insert into `tabSeries` (`name`, `current`) values (%s, %s) on duplicate key update `current` = %s",
			(key, current, current),
		)

	@bru("BRU-ID-001")
	def test_set_id_structure_and_parse_round_trip(self):
		prefix = code_registry.company_prefix()
		self.assertEqual(code_registry.SET_SERIES_MAX, 999999)
		set_id = code_registry.next_set_id("KHAM01")
		self.assertRegex(set_id, rf"^{prefix}KHAM01\d{{6}}$")
		self.assertEqual(gs1.split_set_id(set_id, "KHAM01"), (prefix, set_id[-6:]))
		self.assertEqual(gs1.split_set_id(set_id, "KHAM01", prefix), (prefix, set_id[-6:]))
		self.assertLessEqual(len(set_id), gs1.MAX_GIAI_LENGTH)
		self.assertTrue(set(set_id) <= gs1.CSET82)
		row = frappe.db.get_value(
			"Code Registry", set_id, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
		)
		self.assertEqual(
			row,
			{"prefix": f"{prefix}KHAM01", "ref_doctype": "Set Unit", "ref_name": set_id, "status": "Active"},
		)
		for raw in [
			set_id,
			f"8004{set_id}",
			f"]d2\x1d8004{set_id}",
			f"(8004){set_id}\r\n",
			gs1.giai_payload(set_id),
			gs1.giai_hri(set_id),
		]:
			with self.subTest(raw=raw):
				result = gs1.parse_scan(raw)
				self.assertEqual((result["type"], result["id"]), ("set", set_id))

	def test_set_id_has_no_check_digit(self):
		codes = [code_registry.next_set_id("CRNC") for _ in range(3)]
		heads = {code[:-6] for code in codes}
		self.assertEqual(heads, {self.series_key("CRNC")})
		serials = [int(code[-6:]) for code in codes]
		self.assertEqual(serials, list(range(serials[0], serials[0] + 3)))
		# không có ký tự kiểm: độ dài = tiền tố + mã loại bộ + 6 số
		self.assertTrue(all(len(code) == len(self.series_key("CRNC")) + 6 for code in codes))
		# kiểm GTIN-14 (có check digit) không đổi
		self.assertTrue(gs1.is_valid_gtin14(gs1.make_test_gtin14(1)))
		self.assertFalse(gs1.is_valid_gtin14(gs1.make_test_gtin14(1)[:13] + "0"))

	def test_type_code_ending_in_digits_is_unambiguous(self):
		k1 = [code_registry.next_set_id("K1") for _ in range(3)]
		k10 = [code_registry.next_set_id("K10") for _ in range(3)]
		self.assertEqual(len(set(k1 + k10)), 6)
		prefix = code_registry.company_prefix()
		for code in k1:
			self.assertEqual(gs1.split_set_id(code, "K1"), (prefix, code[-6:]))
			with self.assertRaises(gs1.GS1Error):
				gs1.split_set_id(code, "K10")
		for code in k10:
			self.assertEqual(gs1.split_set_id(code, "K10"), (prefix, code[-6:]))
			with self.assertRaises(gs1.GS1Error):
				gs1.split_set_id(code, "K1")

	def test_set_id_never_matches_instrument_or_bom_patterns(self):
		prefix = code_registry.company_prefix()
		set_id = code_registry.next_set_id("KHAM01")
		self.assertEqual(gs1.parse_scan(set_id)["type"], "set")
		others = {
			f"{prefix}I-00000001": "instrument",
			f"(8004){prefix}I-00000001": "instrument",
			"BOM-KHAM01-V3": "bom",
		}
		for raw, kind in others.items():
			with self.subTest(raw=raw):
				self.assertEqual(gs1.parse_scan(raw)["type"], kind)
				with self.assertRaises(gs1.GS1Error):
					gs1.split_set_id(gs1.clean_scan(raw).removeprefix("(8004)"), "KHAM01")
				self.assertNotEqual(gs1.parse_scan(raw)["id"], set_id)

	def test_next_set_id_series_exhausted(self):
		key = self.series_key("CRX")
		self.set_series(key, code_registry.SET_SERIES_MAX)
		with self.assertRaises(frappe.ValidationError) as raised:
			code_registry.next_set_id("CRX")
		self.assertNotIsInstance(raised.exception, code_registry.CodeAlreadyIssuedError)
		self.assertIn(f"{key}######", str(raised.exception))
		self.assertFalse(code_registry.is_issued(f"{key}1000000"))
		self.assertEqual(frappe.db.count("Code Registry", {"prefix": key}), 0)

	def test_next_set_id_rejects_malformed_type_code(self):
		# phòng thủ nhiều lớp (review Task 1): nơi gọi trực tiếp truyền mã không đúng [A-Z0-9]{2,8} bị từ chối trước getseries
		with patch.object(code_registry, "getseries") as getseries:
			for bad in (
				"I-00",
				"K",
				"ABCDEFGHI",
				"kham",
				"",
				None,
				"KH M",
				"KHAM\n",
				chr(0xFF2B) + chr(0xFF21),
			):
				with self.subTest(type_code=bad):
					with self.assertRaises(frappe.ValidationError):
						code_registry.next_set_id(bad)
			getseries.assert_not_called()

	def test_next_set_id_exhaustion_error_type(self):
		key = self.series_key("CRY")
		self.set_series(key, code_registry.SET_SERIES_MAX)
		with self.assertRaises(code_registry.SeriesExhaustedError):
			code_registry.next_set_id("CRY")

	def test_next_set_id_last_serial_still_issued(self):
		key = self.series_key("CRL")
		self.set_series(key, code_registry.SET_SERIES_MAX - 1)
		self.assertEqual(code_registry.next_set_id("CRL"), f"{key}999999")

	@bru("BRU-ID-001")
	def test_next_set_id_skips_registered_and_never_reissues_disabled(self):
		key = self.series_key("CRD")
		first = code_registry.next_set_id("CRD")
		serial = int(first[-6:])
		manual = f"{key}{serial + 1:06d}"
		disabled = f"{key}{serial + 2:06d}"
		code_registry.register(manual, key, "Set Unit", "manual")
		# không ref: `disable` lưu lại doc và kiểm Link (Set Unit giả không tồn tại)
		code_registry.register(disabled, key)
		code_registry.disable(disabled, "test")
		self.assertEqual(code_registry.next_set_id("CRD"), f"{key}{serial + 3:06d}")
		self.assertEqual(frappe.db.get_value("Code Registry", manual, "ref_name"), "manual")
		self.assertEqual(frappe.db.get_value("Code Registry", disabled, "status"), "Disabled")

	def test_set_prefix_block_demo_outside_dev_test(self):
		from tracecore.core.errors import BlockedError

		conf, flags = production_site(tc_gs1_company_prefix="9520000")
		with conf, flags:
			self.assertFalse(code_registry.demo_prefix_allowed())
			block = code_registry.gs1_prefix_block("9520000", "set")
			self.assertEqual(block.code, "GS1_PREFIX_NOT_CONFIGURED")
			self.assertIn("Set ID", block.reason)
			self.assertIn("9520000", block.reason)
			self.assertNotIn("instrument", block.reason)
			self.assertNotIn("instrument", block.action)
			with patch.object(code_registry, "getseries") as getseries:
				with self.assertRaises(BlockedError) as raised:
					code_registry.next_set_id("CRP")
				getseries.assert_not_called()
			self.assertEqual(raised.exception.block.code, "GS1_PREFIX_NOT_CONFIGURED")
			# chưa cấu hình tiền tố (rơi về tiền tố demo) cũng bị chặn
			with patch.dict(frappe.conf, {"tc_gs1_company_prefix": None}):
				with self.assertRaises(BlockedError):
					code_registry.next_set_id("CRP")
			self.assertIsNone(code_registry.gs1_prefix_block("8930001", "set"))
			with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "8930001"}):
				code = code_registry.next_set_id("CRP")
			self.assertRegex(code, r"^8930001CRP\d{6}$")
		self.assertEqual(frappe.db.count("Code Registry", {"name": ["like", "9520000CRP%"]}), 0)
		# site test: tiền tố demo dùng được
		self.assertIsNone(code_registry.gs1_prefix_block("9520000", "set"))
		# sai định dạng → chặn ở mọi site
		for prefix in ["12a4", "123", "1234567890123", "", None, "\uff19\uff15\uff120000"]:
			with self.subTest(prefix=prefix):
				block = code_registry.gs1_prefix_block(prefix, "set")
				self.assertEqual(block.code, "GS1_PREFIX_NOT_CONFIGURED")
		with self.assertRaises(ValueError):
			code_registry.gs1_prefix_block("8930001", "pack")

	def test_set_id_block_uses_prefix_inside_code(self):
		demo_id = gs1.make_giai("9520000", "KHAM01000001")
		real_id = gs1.make_giai("8930001", "KHAM01000001")
		conf, flags = production_site(tc_gs1_company_prefix="8930001")
		with conf, flags:
			block = code_registry.set_id_block(demo_id, "KHAM01")
			self.assertEqual(block.code, "GS1_PREFIX_NOT_CONFIGURED")
			self.assertIn("9520000", block.reason)
			self.assertIsNone(code_registry.set_id_block(real_id, "KHAM01"))
			# mã không đúng cấu trúc Set ID của loại bộ → chặn, không 500
			for bad in [real_id, "BOM-KHAM01-V3", "", None]:
				with self.subTest(bad=bad):
					block = code_registry.set_id_block(bad, "KHAM02")
					self.assertEqual(block.code, "GS1_PREFIX_NOT_CONFIGURED")
		self.assertIsNone(code_registry.set_id_block(demo_id, "KHAM01"))

	def test_etching_prefix_block_alias_unchanged(self):
		conf, flags = production_site()
		with conf, flags:
			for prefix in ["9520000", "12a4", None]:
				with self.subTest(prefix=prefix):
					block = code_registry.etching_prefix_block(prefix)
					self.assertEqual(block, code_registry.gs1_prefix_block(prefix, "instrument"))
					self.assertEqual(block, code_registry.gs1_prefix_block(prefix))
					title, reason, action = INSTRUMENT_BLOCK_TEXTS
					self.assertEqual(
						(block.code, block.title, block.reason, block.action),
						(
							"GS1_PREFIX_NOT_CONFIGURED",
							frappe._(title),
							frappe._(reason).format(prefix or "-"),
							frappe._(action),
						),
					)
			self.assertIsNone(code_registry.etching_prefix_block("8930001"))
