from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from tracecore.core import step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import washing
from tracecore.tests.factories import (
	make_batch,
	make_chemical_batch,
	make_equipment,
	make_item,
	make_set_unit,
	make_wash_batch,
	make_wash_machine,
	make_wash_program,
	make_wash_ready_set,
)
from tracecore.tests.utils import bru

CHEMICAL = "HC-ENZ-01"


def _code(fn, *args, **kwargs):
	"""Mã lỗi của `BlockedError` mà `fn` ném (None nếu không ném)."""
	try:
		fn(*args, **kwargs)
	except BlockedError as error:
		return error.block.code
	return None


class TestWashingMachine(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_wash_machine()
		self.batch = make_chemical_batch(CHEMICAL)
		self.program = make_wash_program(self.machine.name, chemical=CHEMICAL)

	@bru("BRU-REP-016")
	def test_scan_machine_returns_programs_of_that_machine_only(self):
		other = make_wash_machine()
		make_wash_program(other.name, chemical=CHEMICAL)
		make_wash_program(self.machine.name, chemical=CHEMICAL, is_active=0)
		result = washing.scan_machine(self.machine.name)
		self.assertEqual([p["program_code"] for p in result["programs"]], [self.program.name])
		self.assertEqual(result["programs"][0]["chemical"], CHEMICAL)
		self.assertEqual(result["equipment"].name, self.machine.name)

	def test_scan_machine_returns_door_connection_and_lot_quantity(self):
		result = washing.scan_machine(f"]Q1{self.machine.name}\r\n")
		equipment = result["equipment"]
		self.assertEqual((equipment.zone_in, equipment.zone_out), ("ZONE-DIRTY", None))
		self.assertEqual((equipment.is_connected, equipment.has_printout), (0, 0))
		self.assertEqual(equipment.equipment_type, "Washer-Disinfector")
		lot = next(lot for lot in result["chemical_lots"] if lot["batch_no"] == self.batch.name)
		self.assertEqual((lot["qty"], lot["uom"]), (10, "Nos"))
		self.assertEqual(lot["expiry_date"], getdate(add_days(today(), 60)))

	def test_scan_machine_rejects_codes_that_are_not_a_machine(self):
		for raw in ("TR-004", "ABC", "", "CN-00001"):
			self.assertEqual(_code(washing.scan_machine, raw), "SCAN_INVALID", msg=raw)
		self.assertEqual(_code(washing.scan_machine, "TB-9999"), "EQUIPMENT_NOT_FOUND")

	@bru("BRU-REP-016")
	def test_check_equipment_ready(self):
		self.assertIsNone(washing.check_equipment_ready(self.machine.name))
		steam = make_equipment(
			equipment_type="Steam Sterilizer",
			serial="SS-" + frappe.generate_hash(length=8),
			zone_in="ZONE-CLEAN",
			zone_out="ZONE-STERILE",
		)
		self.assertEqual(washing.check_equipment_ready(steam.name).code, "EQUIPMENT_NOT_WASHER")
		self.assertEqual(washing.check_equipment_ready("TB-9999").code, "EQUIPMENT_NOT_FOUND")
		for status in ("Locked", "Repair", "Retired"):
			frappe.db.set_value("Equipment", self.machine.name, "status", status)
			block = washing.check_equipment_ready(self.machine.name)
			self.assertEqual(block.code, "EQUIPMENT_NOT_READY", msg=status)
			self.assertEqual(block.http_status, 423)
			self.assertIn(self.machine.name, block.reason)
		# máy không Sẵn sàng thì không mở được lô rửa
		self.assertEqual(_code(washing.scan_machine, self.machine.name), "EQUIPMENT_NOT_READY")


class TestWashingAdmit(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_wash_machine()
		self.program = make_wash_program(self.machine.name)

	def _gate(self, unit, step):
		return next(g for g in step_gate.gates(unit) if g["step"] == step)

	def test_admit_returns_gate_panel_data(self):
		unit = make_wash_ready_set()
		result = washing.admit_set(unit.name, self.machine.name, [])
		self.assertEqual(result["set_id"], unit.name)
		self.assertEqual(result["set_type"], unit.set_type)
		self.assertTrue(result["set_name"])
		self.assertFalse(result["duplicate"])
		self.assertEqual([g["step"] for g in result["gates"]], ["T1", "T2", "T3", "T4", "T5"])
		self.assertEqual(self._gate(unit.name, "T1")["result"], "Pass")
		self.assertEqual(result["gates"][1]["result"], "Pending")

	@bru("BRU-FLOW-004")
	def test_admit_rejects_set_without_t1_pass(self):
		unit = make_set_unit()
		step_gate.start_cycle(unit.name)
		with self.assertRaises(BlockedError) as caught:
			washing.admit_set(unit.name, self.machine.name, [])
		self.assertEqual(caught.exception.block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(caught.exception.block.redo_step, "T1")

	def test_admit_rejects_set_that_is_not_at_the_dirty_side(self):
		self.assertEqual(
			_code(washing.admit_set, make_set_unit().name, self.machine.name, []),
			"STATUS_INVALID_FOR_STATION",
		)

	def test_admit_rejects_set_in_running_batch(self):
		unit = make_wash_ready_set()
		batch = make_wash_batch(self.machine, self.program, [unit])
		with self.assertRaises(BlockedError) as caught:
			washing.admit_set(unit.name, self.machine.name, [])
		self.assertEqual(caught.exception.block.code, "SET_IN_OTHER_BATCH")
		self.assertIn(batch.name, caught.exception.block.reason)
		# lô đã đóng thì bộ không còn bị giữ
		frappe.db.set_value("Wash Batch", batch.name, "status", "Passed")
		self.assertFalse(washing.admit_set(unit.name, self.machine.name, [])["duplicate"])

	@bru("BRU-FLOW-004")
	def test_admit_rejects_set_already_washed_pass(self):
		unit = make_wash_ready_set()
		step_gate.record(unit.name, "T2", "Pass")
		self.assertEqual(_code(washing.admit_set, unit.name, self.machine.name, []), "STEP_ALREADY_PASSED")

	@bru("BRU-REP-002")
	def test_admit_accepts_set_failed_at_t2(self):
		unit = make_wash_ready_set()
		step_gate.record(unit.name, "T2", "Fail")
		result = washing.admit_set(unit.name, self.machine.name, [])
		self.assertEqual(result["gates"][1], {"step": "T2", "result": "Fail", "redo_count": 1})

	def test_admit_duplicate_scan_is_not_an_error(self):
		unit = make_wash_ready_set()
		for raw in (unit.name, "]d2\x1d8004" + unit.name + "\r\n", "  " + unit.name + "\t"):
			result = washing.admit_set(raw, self.machine.name, [unit.name])
			self.assertTrue(result["duplicate"], msg=repr(raw))
			self.assertEqual(result["set_id"], unit.name)

	def test_admit_lowercase_scan_resolves_to_stored_set_id(self):
		# Set ID tra theo collation không phân biệt hoa thường: trả mã đã lưu để kiosk nhận ra quét lặp
		unit = make_wash_ready_set()
		lower = unit.name.lower()
		self.assertNotEqual(lower, unit.name)
		self.assertEqual(washing.admit_set(lower, self.machine.name, [])["set_id"], unit.name)
		result = washing.admit_set(lower, self.machine.name, [unit.name])
		self.assertTrue(result["duplicate"])
		self.assertEqual(result["set_id"], unit.name)

	def test_admit_rejects_codes_that_are_not_a_set(self):
		for raw in ("TB-0001", "ABC", ""):
			self.assertEqual(_code(washing.admit_set, raw, self.machine.name, []), "SCAN_INVALID", msg=raw)
		self.assertEqual(
			_code(washing.admit_set, "TR-004", self.machine.name, [make_wash_ready_set().name]),
			"SCAN_INVALID",
		)

	def test_admit_rejects_unknown_set(self):
		giai = make_wash_ready_set().name[:-1] + "9"
		if not frappe.db.exists("Set Unit", giai):
			self.assertEqual(_code(washing.admit_set, giai, self.machine.name, []), "SET_NOT_FOUND")

	def test_admit_checks_the_machine_before_the_set(self):
		unit = make_wash_ready_set()
		frappe.db.set_value("Equipment", self.machine.name, "status", "Locked")
		self.assertEqual(_code(washing.admit_set, unit.name, self.machine.name, []), "EQUIPMENT_NOT_READY")

	@bru("BRU-FLOW-004")
	def test_redo_queue_lists_sets_with_t2_fail(self):
		failed, washed, waiting = make_wash_ready_set(), make_wash_ready_set(), make_wash_ready_set()
		step_gate.record(failed.name, "T2", "Fail")
		step_gate.record(washed.name, "T2", "Pass")
		queue = {row["set_id"]: row for row in washing.redo_queue()}
		self.assertEqual(queue[failed.name]["redo_count"], 1)
		self.assertTrue(queue[failed.name]["set_name"])
		self.assertNotIn(washed.name, queue)
		self.assertNotIn(waiting.name, queue)
		# rửa lại đạt thì ra khỏi hàng đợi; Không đạt lần nữa thì đếm tiếp
		step_gate.record(failed.name, "T2", "Fail")
		self.assertEqual({r["set_id"]: r for r in washing.redo_queue()}[failed.name]["redo_count"], 2)
		step_gate.record(failed.name, "T2", "Pass")
		self.assertNotIn(failed.name, {r["set_id"] for r in washing.redo_queue()})


class TestWashingChemicals(FrappeTestCase):
	@bru("BRU-INV-001")
	def test_suggest_chemical_lots_fefo(self):
		far = make_chemical_batch(CHEMICAL, expiry_days=90)
		near = make_chemical_batch(CHEMICAL, expiry_days=10)
		make_chemical_batch(CHEMICAL, expiry_days=-1)  # đã hết hạn
		make_chemical_batch(CHEMICAL, expiry_days=30, qty=0)  # hết tồn
		lots = [lot["batch_no"] for lot in washing.suggest_chemical_lots(CHEMICAL)]
		self.assertLess(lots.index(near.name), lots.index(far.name))
		mine = {lot["batch_no"] for lot in washing.suggest_chemical_lots(CHEMICAL)}
		self.assertTrue({near.name, far.name} <= mine)
		for lot in washing.suggest_chemical_lots(CHEMICAL):
			self.assertGreater(lot["qty"], 0)
			self.assertGreaterEqual(lot["expiry_date"], getdate(today()))
			self.assertEqual(lot["item"], CHEMICAL)

	@bru("BRU-INV-001")
	def test_check_chemical_lot_rules(self):
		ok = make_chemical_batch(CHEMICAL, expiry_days=30)
		today_lot = make_chemical_batch(CHEMICAL, expiry_days=0)
		expired = make_chemical_batch(CHEMICAL, expiry_days=-1)
		other = make_chemical_batch("HC-OTHER-01")
		make_item("PK-WASH-01", "Packaging")
		pack_lot = make_batch(
			"PK-WASH-01", "PK-WASH-LOT-" + frappe.generate_hash(length=6), add_days(today(), 30)
		)
		self.assertIsNone(washing.check_chemical_lot(CHEMICAL, ok.name))
		self.assertIsNone(
			washing.check_chemical_lot(CHEMICAL, today_lot.name)
		)  # hạn đúng hôm nay vẫn dùng được
		block = washing.check_chemical_lot(CHEMICAL, expired.name)
		self.assertEqual((block.code, block.http_status), ("CHEMICAL_LOT_EXPIRED", 422))
		self.assertIn(expired.name, block.reason)
		for item, lot in (
			(CHEMICAL, other.name),  # lô của hóa chất khác
			(CHEMICAL, "NO-SUCH-LOT"),
			("PK-WASH-01", pack_lot.name),  # không thuộc nhóm hóa chất
		):
			self.assertEqual(washing.check_chemical_lot(item, lot).code, "CHEMICAL_LOT_INVALID", msg=lot)
		frappe.db.set_value("Batch", ok.name, "disabled", 1)
		self.assertEqual(washing.check_chemical_lot(CHEMICAL, ok.name).code, "CHEMICAL_LOT_INVALID")

	def test_chemical_expiry_uses_the_system_date_not_utc(self):
		# 00:30 ngày 23/10 giờ Việt Nam: lô hết hạn 22/10 đã hết hạn, lô hết hạn 23/10 còn dùng được
		last_night = make_chemical_batch(CHEMICAL, expiry_days=0)
		frappe.db.set_value("Batch", last_night.name, "expiry_date", "2026-10-22")
		this_day = make_chemical_batch(CHEMICAL, expiry_days=0)
		frappe.db.set_value("Batch", this_day.name, "expiry_date", "2026-10-23")
		with patch("tracecore.reprocessing.washing.now_datetime", return_value=datetime(2026, 10, 23, 0, 30)):
			self.assertEqual(
				washing.check_chemical_lot(CHEMICAL, last_night.name).code, "CHEMICAL_LOT_EXPIRED"
			)
			self.assertIsNone(washing.check_chemical_lot(CHEMICAL, this_day.name))
			lots = {lot["batch_no"] for lot in washing.suggest_chemical_lots(CHEMICAL)}
			self.assertNotIn(last_night.name, lots)
			self.assertIn(this_day.name, lots)
