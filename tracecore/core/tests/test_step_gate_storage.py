"""Cổng T6 của core.step_gate (FEAT-025): kiểm bộ Vô khuẩn trước khi nhập kho, đưa bộ về Chờ tiếp nhận."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import step_gate
from tracecore.tests.factories import make_cycle, make_set_unit
from tracecore.tests.utils import bru


def _status(set_unit):
	return frappe.db.get_value(
		"Set Unit", set_unit, ["status", "active_cycle_id", "current_station"], as_dict=True
	)


class TestStepGateStorage(FrappeTestCase):
	@bru("BRU-FLOW-004")
	def test_check_stored_passes_when_all_five_gates_pass(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3", "T4", "T5"))
		self.assertEqual(_status(su).status, "Sterile")
		self.assertIsNone(step_gate.check_stored(su))

	@bru("BRU-FLOW-004")
	def test_check_stored_lists_missing_steps(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3"))
		block = step_gate.check_stored(su)
		self.assertEqual(block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(block.items, ["T4", "T5"])
		self.assertEqual(block.redo_step, "T4")

	def test_check_stored_set_without_cycle_is_blocked(self):
		su = make_set_unit().name
		block = step_gate.check_stored(su)
		self.assertEqual(block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(block.items, list(step_gate.STEPS))

	def test_check_stored_unknown_set(self):
		with self.assertRaises(frappe.DoesNotExistError):
			step_gate.check_stored("khong-co-bo")

	@bru("BRU-ID-003")
	def test_return_to_receipt_sets_awaiting_receipt_and_clears_cycle_id(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3", "T4", "T5"))
		step_gate.bind_cycle(su, "CY-261020-0001", "TR-006")
		step_gate.return_to_receipt(su)
		state = _status(su)
		self.assertEqual(state.status, "Awaiting Receipt")
		self.assertIsNone(state.active_cycle_id)

	def test_return_to_receipt_only_from_sterile(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3"))
		with self.assertRaises(frappe.ValidationError):
			step_gate.return_to_receipt(su)
		self.assertEqual(_status(su).status, "Processing")

	def test_return_to_receipt_not_allowed_outside_step_gate(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3", "T4", "T5"))
		unit = frappe.get_doc("Set Unit", su)
		unit.status = "Awaiting Receipt"
		with self.assertRaises(frappe.ValidationError):
			unit.save(ignore_permissions=True)

	@bru("BRU-FLOW-003")
	def test_issue_to_department_moves_sterile_set_to_department(self):
		# FEAT-026 C3: cấp phát T7 đưa bộ Vô khuẩn sang Tại khoa, giữ Cycle ID (gói còn dùng ở T8) và ghi trạm T7
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3", "T4", "T5"))
		step_gate.bind_cycle(su, "CY-261023-0001", "TR-006")
		step_gate.issue_to_department(su, "TR-007")
		state = _status(su)
		self.assertEqual(state.status, "At Department")
		self.assertEqual(state.active_cycle_id, "CY-261023-0001")
		self.assertEqual(state.current_station, "TR-007")

	@bru("BRU-FLOW-003")
	def test_issue_to_department_only_from_sterile(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3", "T4"))
		with self.assertRaises(frappe.ValidationError):
			step_gate.issue_to_department(su, "TR-007")
		self.assertEqual(_status(su).status, "Processing")

	def test_start_cycle_after_awaiting_receipt_reopens_processing(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3", "T4", "T5"))
		step_gate.return_to_receipt(su)
		self.assertEqual(step_gate.start_cycle(su), 2)
		self.assertEqual(_status(su).status, "Processing")


class TestStepGateCountCycle(FrappeTestCase):
	@bru("BRU-FLOW-003")
	def test_count_cycle_adds_one_cycle_used_through_the_step_gate_only(self):
		# FEAT-023 D6: mẻ giải phóng Đạt tăng bộ đếm chu trình của bộ; chỉ step_gate đổi được cycles_used
		su = make_set_unit().name
		before = frappe.db.get_value("Set Unit", su, "cycles_used")
		self.assertEqual(step_gate.count_cycle(su), before + 1)
		self.assertEqual(step_gate.count_cycle(su), before + 2)
		self.assertEqual(frappe.db.get_value("Set Unit", su, "cycles_used"), before + 2)
		unit = frappe.get_doc("Set Unit", su)
		unit.cycles_used = before
		with self.assertRaises(frappe.ValidationError):
			unit.save(ignore_permissions=True)
