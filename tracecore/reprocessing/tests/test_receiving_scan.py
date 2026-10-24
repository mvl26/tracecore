"""Quét bộ vào phiếu tiếp nhận T1 (FEAT-019 Task 4; FR-M2-01.1/.2/.5/.6, FR-M2-02/.1/.2, FR-M2-23; AC-02..04, AC-06..08)."""

from datetime import timedelta

import frappe

from tracecore.core import gs1, station_auth
from tracecore.reprocessing import receiving
from tracecore.reprocessing.tests.receiving_case import BOM, STATION, ReceivingCase
from tracecore.tests.factories import make_user
from tracecore.tests.utils import bru
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestReceivingScan(ReceivingCase):
	def setUp(self):
		super().setUp()
		self.receipt = self.opened()

	@bru("BRU-FLOW-002")
	def test_sets_new_at_department_and_awaiting_receipt_are_accepted(self):
		for status in ("New", "At Department", "Awaiting Receipt"):
			unit = self.new_set(status)
			result = self.scan(self.receipt, unit)
			self.assertFalse(result["duplicate"], status)
			self.assertEqual(result["item"]["status_before"], status)
		self.assertEqual(len(frappe.get_doc("Dirty Receipt", self.receipt).items), 3)

	@bru("BRU-REP-012")
	def test_item_lists_every_bom_line_in_order_with_photos_and_no_tick(self):
		unit = self.new_set()
		item = self.scan(self.receipt, unit)["item"]
		self.assertEqual(item["set_id"], unit)
		self.assertEqual(item["bom_version"], 1)
		self.assertEqual([line["instrument"] for line in item["lines"]], [code for code, _qty in BOM])
		self.assertEqual([line["qty"] for line in item["lines"]], [qty for _code, qty in BOM])
		self.assertEqual([line["position"] for line in item["lines"]], [1, 2, 3])
		self.assertFalse(any(line["confirmed"] for line in item["lines"]))
		for line in item["lines"]:
			self.assertTrue(line["instrument_name"])
			self.assertIn("thumbnail", line)  # None → khung "Chưa có ảnh" (FR-M2-23.7)
		self.assertEqual((item["confirmed"], item["needs_review"], item["tray_images"]), (0, 0, []))

	def test_receipt_view_counts_received_and_flagged_sets(self):
		first = self.scan(self.receipt, self.new_set())
		self.assertEqual((first["summary"]["set_count"], first["summary"]["flagged_count"]), (1, 0))
		self.scan(self.receipt, self.new_set())
		view = self.scan(self.receipt, self.new_set())["summary"]
		self.assertEqual(view["set_count"], 3)
		resumed = self.open()  # mở lại phiếu: bộ chờ xác nhận đầu tiên hiện đủ dòng BOM
		self.assertEqual(resumed["current"]["set_id"], resumed["items"][0]["set_id"])
		self.assertEqual(len(resumed["current"]["lines"]), len(BOM))

	@bru("BRU-FLOW-002")
	@bru("BRU-FLOW-003")
	def test_wrong_status_is_refused_with_reason_and_current_station(self):
		unit = self.new_set("Sterile")
		frappe.db.set_value("Set Unit", unit, "current_station", "TR-006")
		with self.assertRaises(receiving.BlockedError) as caught:
			self.scan(self.receipt, unit)
		block = caught.exception.block
		self.assertEqual(block.code, "STATUS_INVALID_FOR_STATION")
		self.assertIn(unit, block.reason)
		self.assertIn("TR-006", block.reason)  # FR-M2-02.1: trạm hiện tại của bộ
		self.assertTrue(block.action)
		self.assertEqual(frappe.get_doc("Dirty Receipt", self.receipt).items, [])

	@bru("BRU-FLOW-003")
	def test_mid_cycle_set_names_the_step_it_is_waiting_at(self):
		unit = self.new_set("Processing")
		frappe.db.set_value("Set Unit", unit, "current_cycle_no", 1)
		with self.assertRaises(receiving.BlockedError) as caught:
			self.scan(self.receipt, unit)
		self.assertIn("T1", caught.exception.block.reason)  # cổng đầu tiên chưa Đạt của chu trình

	def test_end_of_life_set_is_refused(self):
		self.assertEqual(
			self.code_of(self.scan, self.receipt, self.new_set("End of Life")), "SET_END_OF_LIFE"
		)

	@bru("BRU-FLOW-002")
	def test_duplicate_scan_adds_no_second_row(self):
		unit = self.new_set()
		self.scan(self.receipt, unit)
		again = self.scan(self.receipt, unit)
		self.assertTrue(again["duplicate"])
		self.assertEqual(again["item"]["set_id"], unit)
		doc = frappe.get_doc("Dirty Receipt", self.receipt)
		self.assertEqual((len(doc.items), len(doc.confirm_lines)), (1, len(BOM)))

	@bru("BRU-ID-006")
	def test_only_set_codes_are_accepted_inside_an_open_receipt(self):
		self.assertEqual(self.code_of(self.scan, self.receipt, "NOT-A-CODE"), "SCAN_INVALID")
		self.assertEqual(self.code_of(self.scan, self.receipt, "TB-0001"), "SCAN_INVALID")
		# thẻ người giao quét một lần cho cả phiếu: thẻ thứ hai không đổi người giao (FR-M2-01.1)
		self.assertEqual(self.code_of(self.scan, self.receipt, self.card), "SCAN_INVALID")
		self.assertEqual(self.code_of(self.scan, self.receipt, "NV-12345"), "SCAN_INVALID")
		prefix = gs1.configured_company_prefix()
		unknown = gs1.make_giai(prefix, "RCV1999999")
		self.assertEqual(self.code_of(self.scan, self.receipt, unknown), "SCAN_INVALID")

	def test_scan_in_a_closed_receipt_is_refused(self):
		receiving.discard(self.receipt, STATION, self.receiver)
		self.assertEqual(self.code_of(self.scan, self.receipt, self.new_set()), "RECEIPT_CLOSED")

	def test_station_clock_far_from_the_server_clock_is_refused(self):
		stale = self.now() - timedelta(hours=3)
		with self.assertRaises(frappe.ValidationError):
			self.scan(self.receipt, self.new_set(), client_ts=stale)

	@bru("BRU-REP-012")
	def test_bom_version_follows_the_scan_day_in_the_system_time_zone(self):
		# 23:30 UTC = 06:30 hôm sau giờ Việt Nam: ngày hệ thống quyết định phiên bản BOM
		unit = self.new_set()
		item = self.scan(self.receipt, unit)["item"]
		doc = frappe.get_doc("Dirty Receipt", self.receipt)
		self.assertEqual(doc.items[0].bom_version, item["bom_version"])
		self.assertEqual(doc.items[0].received_at.date(), (self.now() + timedelta(hours=7)).date())


class TestForcedReceipt(ReceivingCase):
	def setUp(self):
		super().setUp()
		self.receipt = self.opened()
		self.r02 = make_user("t1-force-r02@test.local", roles=("TC R02",))
		self.r03 = make_user("t1-force-r03@test.local", roles=("TC R03",))

	def proof_of(self, user, pin="246810"):
		session = make_station_session(user, station=STATION)
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		frappe.db.set_value("Employee", employee, "tc_pin_reset_required", 0)
		station_auth.set_pin(employee, pin)
		proof = station_auth.create_pin_proof(session["token"], pin)["proof"]
		return session["session"], proof

	def force(self, unit, session=None, proof=None, reason="Returned early from the ward"):
		return self.scan(self.receipt, unit, force_reason=reason, session=session, reviewer_proof=proof)

	@bru("BRU-FLOW-002")
	def test_r02_with_pin_proof_and_reason_receives_a_refused_set(self):
		unit = self.new_set("Sterile")
		session, proof = self.proof_of(self.r02)
		item = self.force(unit, session, proof)["item"]
		self.assertEqual((item["forced"], item["force_reason"]), (1, "Returned early from the ward"))
		row = frappe.get_doc("Dirty Receipt", self.receipt).items[0]
		self.assertEqual((row.forced, row.forced_by), (1, self.r02))

	def test_force_needs_a_reason(self):
		session, proof = self.proof_of(self.r02)
		self.assertEqual(
			self.code_of(self.force, self.new_set("Sterile"), session, proof, reason="  "), "REASON_REQUIRED"
		)

	def test_force_needs_r02_and_a_valid_one_time_proof(self):
		unit = self.new_set("Sterile")
		self.assertEqual(self.code_of(self.force, unit), "R02_CONFIRM_REQUIRED")  # không có proof
		session, _proof = self.proof_of(self.r02)
		self.assertEqual(self.code_of(self.force, unit, session, "sai"), "R02_CONFIRM_REQUIRED")
		r03_session, r03_proof = self.proof_of(self.r03)
		self.assertEqual(self.code_of(self.force, unit, r03_session, r03_proof), "R02_CONFIRM_REQUIRED")
		session, proof = self.proof_of(self.r02)
		self.force(unit, session, proof)
		self.assertEqual(
			self.code_of(self.force, self.new_set("Sterile"), session, proof), "R02_CONFIRM_REQUIRED"
		)

	def test_disposed_and_end_of_life_cannot_be_forced(self):
		session, proof = self.proof_of(self.r02)
		for status in ("Disposed", "End of Life"):
			self.assertEqual(
				self.code_of(self.force, self.new_set(status), session, proof), "FORCE_NOT_ALLOWED"
			)

	def test_forcing_a_set_that_needs_no_force_is_an_ordinary_receipt(self):
		session, proof = self.proof_of(self.r02)
		item = self.force(self.new_set("At Department"), session, proof)["item"]
		self.assertEqual(item["forced"], 0)
