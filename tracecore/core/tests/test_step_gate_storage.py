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

	def test_start_cycle_after_awaiting_receipt_reopens_processing(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3", "T4", "T5"))
		step_gate.return_to_receipt(su)
		self.assertEqual(step_gate.start_cycle(su), 2)
		self.assertEqual(_status(su).status, "Processing")
