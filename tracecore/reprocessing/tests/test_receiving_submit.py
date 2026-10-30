"""Ghi sổ phiếu tiếp nhận T1 (FEAT-019 Task 6; FR-M2-01.3, FR-M2-01.4, FR-M2-23.3/.4, FR-M2-25; AC-11, AC-12)."""

from datetime import datetime, time, timedelta
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import client_time, code_registry, step_gate
from tracecore.reprocessing import receiving
from tracecore.reprocessing.tests.receiving_case import STATION, ReceivingCase
from tracecore.tests.factories import make_bom, make_cycle, make_released_pack, make_user
from tracecore.tests.utils import bru
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class SubmitCase(ReceivingCase):
	def setUp(self):
		super().setUp()
		self.receipt = self.opened()

	def received(self, status="At Department", note=None, confirm=True, **scan):
		"""Bộ ở `status` đã quét vào phiếu và (mặc định) Xác nhận bộ."""
		unit = self.new_set(status)
		self.scan(self.receipt, unit, **scan)
		if confirm:
			receiving.confirm_line(
				self.receipt, unit, STATION, self.receiver, confirm_all=True, note=note, finalize=True
			)
		return unit

	def submit(self, **kwargs):
		kwargs.setdefault("client_ts", self.now())
		return receiving.submit(self.receipt, STATION, self.receiver, **kwargs)

	def gate(self, unit, cycle_no=1):
		return frappe.db.get_value(
			"Step Gate Result",
			f"{unit}-C{cycle_no}-T1",
			["result", "ref_doctype", "ref_name", "station"],
			as_dict=True,
		)


class TestReceivingSubmit(SubmitCase):
	@bru("BRU-FLOW-004")
	def test_submit_opens_the_cycle_records_gate_t1_and_moves_sets_to_wait_for_washing(self):
		first, second = self.received("At Department"), self.received("New")
		result = self.submit()
		self.assertEqual(result["receipt"], self.receipt)
		self.assertEqual(sorted(result["sets"]), sorted([first, second]))
		self.assertEqual(result["rejected"], [])
		for unit in (first, second):
			state = frappe.db.get_value("Set Unit", unit, ["status", "current_cycle_no"], as_dict=True)
			self.assertEqual((state.status, state.current_cycle_no), ("Processing", 1))
			self.assertEqual(
				self.gate(unit),
				{
					"result": "Pass",
					"ref_doctype": "Dirty Receipt",
					"ref_name": self.receipt,
					"station": STATION,
				},
			)
			self.assertIsNone(step_gate.check(unit, "T2"))  # sẵn sàng vào lô rửa
		doc = frappe.get_doc("Dirty Receipt", self.receipt)
		self.assertEqual(
			(doc.docstatus, doc.set_count, doc.receiver, doc.station), (1, 2, self.receiver, STATION)
		)
		self.assertTrue(doc.received_at)
		self.assertEqual({item.cycle_no for item in doc.items}, {1})

	@bru("BRU-FLOW-004")
	def test_returning_set_gets_the_next_cycle_number(self):
		unit = self.received("Awaiting Receipt")
		frappe.db.set_value("Set Unit", unit, "current_cycle_no", 3, update_modified=False)
		self.submit()
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "current_cycle_no"), 4)
		self.assertEqual(self.gate(unit, 4)["result"], "Pass")

	@bru("BRU-REP-012")
	def test_set_with_abnormal_note_is_flagged_for_review(self):
		plain, flagged = self.received(), self.received(note="Thiếu 1 kẹp")
		result = self.submit()
		self.assertEqual(result["flagged"], [flagged])
		doc = frappe.get_doc("Dirty Receipt", self.receipt)
		self.assertEqual(doc.flagged_count, 1)
		by_set = {item.set_unit: item for item in doc.items}
		self.assertEqual((by_set[plain].needs_review, by_set[flagged].needs_review), (0, 1))
		self.assertEqual(by_set[flagged].abnormal_note, "Thiếu 1 kẹp")

	def test_unconfirmed_set_blocks_the_whole_submit(self):
		done, waiting = self.received(), self.received(confirm=False)
		with self.assertRaises(receiving.BlockedError) as caught:
			self.submit()
		block = caught.exception.block
		self.assertEqual((block.code, block.items), ("ITEM_NOT_CONFIRMED", [waiting]))
		self.assertEqual(frappe.db.get_value("Dirty Receipt", self.receipt, "docstatus"), 0)
		self.assertEqual(frappe.db.get_value("Set Unit", done, "status"), "At Department")

	def test_empty_receipt_cannot_be_submitted(self):
		self.assertEqual(self.code_of(self.submit), "RECEIPT_EMPTY")

	def test_submitted_receipt_is_closed(self):
		self.received()
		self.submit()
		self.assertEqual(self.code_of(self.submit), "RECEIPT_CLOSED")
		self.assertEqual(self.code_of(self.scan, self.receipt, self.new_set()), "RECEIPT_CLOSED")

	@bru("BRU-FLOW-002")
	def test_set_taken_by_another_receipt_meanwhile_is_dropped_not_stuck(self):
		kept, taken = self.received(), self.received()
		frappe.db.set_value("Set Unit", taken, "status", "Processing", update_modified=False)
		result = self.submit()
		self.assertEqual(result["sets"], [kept])
		self.assertEqual([row["set_id"] for row in result["rejected"]], [taken])
		self.assertEqual(result["rejected"][0]["code"], "STATUS_INVALID_FOR_STATION")
		doc = frappe.get_doc("Dirty Receipt", self.receipt)
		self.assertEqual([item.set_unit for item in doc.items], [kept])
		self.assertEqual([line.set_unit for line in doc.confirm_lines if line.set_unit == taken], [])
		self.assertEqual(doc.set_count, 1)

	def test_all_sets_taken_leaves_the_draft_open(self):
		taken = self.received()
		frappe.db.set_value("Set Unit", taken, "status", "Processing", update_modified=False)
		with self.assertRaises(receiving.BlockedError) as caught:
			self.submit()
		self.assertEqual(caught.exception.block.code, "RECEIPT_EMPTY")
		self.assertEqual(frappe.db.get_value("Dirty Receipt", self.receipt, "docstatus"), 0)

	def test_failure_in_the_middle_rolls_everything_back(self):
		first, second = self.received(), self.received()
		real = step_gate.record
		calls = []

		def flaky(*args, **kwargs):
			calls.append(args[0])
			if len(calls) == 2:
				raise RuntimeError("boom")
			return real(*args, **kwargs)

		with patch("tracecore.reprocessing.receiving.step_gate.record", side_effect=flaky):
			with self.assertRaises(RuntimeError):
				self.submit()
		for unit in (first, second):
			self.assertEqual(
				frappe.db.get_value("Set Unit", unit, ["status", "current_cycle_no"]), ("At Department", 0)
			)
		self.assertEqual(frappe.db.get_value("Dirty Receipt", self.receipt, "docstatus"), 0)


class TestReceivingBomPin(SubmitCase):
	@bru("BRU-REP-012")
	def test_scan_after_midnight_vietnam_time_pins_the_bom_of_that_vietnam_day(self):
		# BOM v2 hiệu lực từ ngày mai (giờ hệ thống). Quét lúc 06:30 sáng mai giờ VN = 23:30 UTC hôm nay: nếu dùng
		# nhầm ngày UTC thì ghim v1 (phiên bản của ngày hôm trước).
		make_bom(self.set_type, [("RV-KC-01", 5)], version=2, effective_from=add_days(today(), 1))
		scan_at = datetime.combine(getdate(add_days(today(), 1)), time(6, 30)) - timedelta(hours=7)
		self.assertEqual(client_time.to_system_time(scan_at).date(), getdate(add_days(today(), 1)))
		self.assertEqual(scan_at.date(), getdate(today()))
		with patch("tracecore.reprocessing.receiving.client_time.check_skew"):
			unit = self.received(client_ts=scan_at)
			item = frappe.get_doc("Dirty Receipt", self.receipt).items[0]
			self.assertEqual(item.bom_version, 2)
			with patch.object(step_gate, "start_cycle", wraps=step_gate.start_cycle) as start:
				self.submit(client_ts=scan_at)
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "cycle_bom_version"), 2)
		args, kwargs = start.call_args
		self.assertEqual(args[0], unit)
		self.assertEqual(kwargs["on"], client_time.to_system_time(scan_at))  # giờ hệ thống, không phải UTC
		self.assertEqual(kwargs["client_ts"], scan_at)

	def test_scan_today_pins_todays_version(self):
		make_bom(self.set_type, [("RV-KC-01", 5)], version=2, effective_from=add_days(today(), 1))
		unit = self.received()
		self.submit()
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "cycle_bom_version"), 1)


class TestReceivingUnusedCycleId(SubmitCase):
	def issued_set(self, pack_status):
		pack = make_released_pack(status=pack_status, set_type=self.set_type)
		unit = pack.set_unit
		frappe.db.set_value("Set Unit", unit, "status", "At Department", update_modified=False)
		return unit, pack.name

	@bru("BRU-REP-001")
	@bru("BRU-ID-003")
	def test_unused_cycle_id_is_voided_with_reason_returned_unused(self):
		unit, cycle_id = self.issued_set("Issued")
		self.scan(self.receipt, unit)
		receiving.confirm_line(self.receipt, unit, STATION, self.receiver, confirm_all=True, finalize=True)
		self.submit()
		pack = frappe.get_doc("Pack", cycle_id)
		self.assertEqual((pack.status, pack.void_reason), ("Void", "Returned Unused"))
		self.assertIn(self.receipt, pack.void_note)
		self.assertEqual(frappe.db.get_value("Code Registry", cycle_id, "status"), "Disabled")
		self.assertIsNone(frappe.db.get_value("Set Unit", unit, "active_cycle_id"))
		item = frappe.get_doc("Dirty Receipt", self.receipt).items[0]
		self.assertEqual(item.voided_pack, cycle_id)

	@bru("BRU-ID-003")
	def test_used_cycle_id_is_left_alone(self):
		unit, cycle_id = self.issued_set("Used")
		self.scan(self.receipt, unit)
		receiving.confirm_line(self.receipt, unit, STATION, self.receiver, confirm_all=True, finalize=True)
		self.submit()
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "Used")
		self.assertTrue(code_registry.is_issued(cycle_id))
		self.assertEqual(frappe.db.get_value("Code Registry", cycle_id, "status"), "Active")
		self.assertFalse(frappe.get_doc("Dirty Receipt", self.receipt).items[0].voided_pack)


class TestForcedSubmit(SubmitCase):
	def setUp(self):
		super().setUp()
		from tracecore.core import station_auth

		self.r02 = make_user("t1-submit-r02@test.local", roles=("TC R02",))
		session = make_station_session(self.r02, station=STATION)
		employee = frappe.db.get_value("Employee", {"user_id": self.r02}, "name")
		frappe.db.set_value("Employee", employee, "tc_pin_reset_required", 0)
		station_auth.set_pin(employee, "246810")
		self.proof = station_auth.create_pin_proof(session["token"], "246810")["proof"]
		self.session = session["session"]

	@bru("BRU-FLOW-002")
	def test_forced_sterile_set_restarts_its_cycle_voids_the_pack_and_calls_the_hook(self):
		pack = make_released_pack(set_type=self.set_type)
		unit = pack.set_unit
		self.scan(
			self.receipt,
			unit,
			force_reason="Returned by mistake",
			session=self.session,
			reviewer_proof=self.proof,
		)
		receiving.confirm_line(self.receipt, unit, STATION, self.receiver, confirm_all=True, finalize=True)
		real = receiving.extension.run
		calls = []

		def spy(hook, *args, **kwargs):
			calls.append((hook, args))
			return real(hook, *args, **kwargs)

		with patch("tracecore.reprocessing.receiving.extension.run", side_effect=spy):
			self.submit()
		self.assertEqual(
			frappe.db.get_value("Set Unit", unit, ["status", "current_cycle_no"]), ("Processing", 2)
		)
		self.assertEqual(
			frappe.db.get_value("Pack", pack.name, ["status", "void_reason"]), ("Void", "Returned Unused")
		)
		forced = [args[0] for hook, args in calls if hook == receiving.AFTER_FORCE_HOOK]
		self.assertEqual(len(forced), 1)
		self.assertEqual(
			(forced[0]["receipt"], forced[0]["set_unit"], forced[0]["reason"], forced[0]["by"]),
			(self.receipt, unit, "Returned by mistake", self.r02),
		)

	def test_forced_set_that_became_disposed_is_dropped(self):
		unit = self.new_set("Sterile")
		self.scan(self.receipt, unit, force_reason="x", session=self.session, reviewer_proof=self.proof)
		receiving.confirm_line(self.receipt, unit, STATION, self.receiver, confirm_all=True, finalize=True)
		other = self.received()
		frappe.db.set_value("Set Unit", unit, "status", "Disposed", update_modified=False)
		result = self.submit()
		self.assertEqual(result["sets"], [other])
		self.assertEqual(result["rejected"][0]["code"], "FORCE_NOT_ALLOWED")
