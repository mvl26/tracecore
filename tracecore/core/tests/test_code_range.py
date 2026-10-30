"""Dải Cycle ID cấp trước cho trạm dùng offline (FEAT-009 Task 2; FR-M9-06.2, FR-M2-07.11; A-40 Q4)."""

import uuid
from datetime import date, datetime, timedelta

import frappe

from tracecore.core import code_range, code_registry, gs1
from tracecore.core.errors import BlockedError
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import code_range as code_range_api
from tracecore.v1.tests.station_fixtures import make_station_session

STATION = "TR-004"
OTHER_STATION = "TR-001"
DAY = date(2026, 10, 26)


class TestAllocate(IsolatedTestCase):
	def test_allocate_200_codes_station_prefix(self):
		row = code_range.allocate(STATION, DAY)
		self.assertEqual(row["prefix"], "CY-261026-T004-")
		self.assertEqual(row["to_no"] - row["from_no"] + 1, code_range.SIZE)
		self.assertEqual(code_range.SIZE, 200)
		self.assertEqual(row["expires_at"], datetime(2026, 10, 27, 0, 0))
		doc = frappe.get_doc("Code Range", row["name"])
		self.assertEqual((doc.station, str(doc.range_date)), (STATION, "2026-10-26"))

	def test_second_allocate_continues_series(self):
		first = code_range.allocate(STATION, DAY)
		second = code_range.allocate(STATION, DAY)
		self.assertEqual(second["from_no"], first["to_no"] + 1)
		self.assertEqual(second["to_no"], first["to_no"] + code_range.SIZE)

	def test_allocate_refills_below_20_percent(self):
		first = code_range.allocate(STATION, DAY)
		self.assertEqual(len(code_range.ensure(STATION, DAY)), 1)  # còn đủ: không cấp thêm
		for number in range(first["from_no"], first["from_no"] + 161):  # dùng 161/200 → còn 39 < 40
			code_registry.register(f"{first['prefix']}{number:04d}", "CY", "Pack", None, STATION)
		ranges = code_range.ensure(STATION, DAY)
		self.assertEqual(len(ranges), 2)
		self.assertEqual(ranges[1]["from_no"], first["to_no"] + 1)

	def test_ensure_allocates_first_range(self):
		ranges = code_range.ensure(STATION, DAY)
		self.assertEqual(len(ranges), 1)

	def test_ensure_reports_used_numbers(self):
		"""Kiosk mất dữ liệu cục bộ (trình duyệt mới, đổi PDA) không cấp lại số đã ghi sổ trên server."""
		first = code_range.allocate(STATION, DAY)
		for number in (first["from_no"], first["from_no"] + 2):
			code_registry.register(f"{first['prefix']}{number:04d}", "CY", "Pack", None, STATION)
		ranges = code_range.ensure(STATION, DAY)
		self.assertEqual(ranges[0]["used"], [first["from_no"], first["from_no"] + 2])


class TestClaim(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.range = code_range.allocate(STATION, DAY)
		self.code = f"{self.range['prefix']}{self.range['from_no']:04d}"

	def assert_invalid(self, code, station=STATION, on=DAY):
		with self.assertRaises(BlockedError) as caught:
			code_range.claim(code, station, on)
		self.assertEqual(caught.exception.block.code, "CODE_RANGE_INVALID")
		self.assertEqual(caught.exception.block.http_status, 409)

	def test_claim_registers_code(self):
		code_range.claim(self.code, STATION, DAY)
		row = frappe.db.get_value(
			"Code Registry", self.code, ["prefix", "ref_doctype", "issued_at"], as_dict=True
		)
		self.assertEqual((row.prefix, row.ref_doctype, row.issued_at), ("CY", "Pack", STATION))

	def test_claim_rejects_other_station(self):
		self.assert_invalid(self.code, station=OTHER_STATION)

	def test_claim_rejects_other_day(self):
		self.assert_invalid(self.code, on=DAY + timedelta(days=1))

	def test_claim_rejects_used_code(self):
		code_range.claim(self.code, STATION, DAY)
		self.assert_invalid(self.code)

	def test_claim_rejects_number_outside_issued_ranges(self):
		self.assert_invalid(f"{self.range['prefix']}{self.range['to_no'] + 1:04d}")

	def test_claim_rejects_malformed(self):
		self.assert_invalid("CY-261026-0001")


class TestParseOfflineCycleId(IsolatedTestCase):
	def test_parse_scan_offline_cycle_id(self):
		for code in ("CY-261026-T004-0001", "CY-261026-T04-0001"):
			scan = gs1.parse_scan(code)
			self.assertEqual((scan["type"], scan["id"]), ("pack", code))


class TestAllocateApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.get_doc("User", "Administrator").add_roles("TC R10", "TC R04")
		self.token = make_station_session("Administrator")["token"]

	def test_allocate_rpc_returns_today_ranges(self):
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4()), "X-TC-Station": STATION}):
			result = code_range_api.allocate(
				station=STATION, client_ts=datetime.now().astimezone().isoformat(), token=self.token
			)
		self.assertIs(result["ok"], True)
		self.assertEqual(len(result["ranges"]), 1)
		self.assertTrue(result["ranges"][0]["prefix"].endswith("-T004-"))
