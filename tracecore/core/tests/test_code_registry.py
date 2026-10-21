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
