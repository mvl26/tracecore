import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import step_gate
from tracecore.core.errors import Block
from tracecore.tests.factories import make_assembly_record, make_cycle, make_set_unit
from tracecore.tests.utils import bru


def _gate(set_unit, step, cycle_no=1):
	return frappe.db.get_value(
		"Step Gate Result", f"{set_unit}-C{cycle_no}-{step}", ["result", "redo_count"], as_dict=True
	)


def _lifecycle(set_unit):
	return frappe.db.get_value(
		"Set Unit",
		set_unit,
		["status", "current_cycle_no", "active_cycle_id", "current_station"],
		as_dict=True,
	)


class TestStepGate(FrappeTestCase):
	def test_start_cycle_increments(self):
		su = make_set_unit().name
		self.assertEqual(_lifecycle(su).current_cycle_no, 0)
		self.assertEqual(step_gate.start_cycle(su), 1)
		self.assertEqual(_lifecycle(su).status, "Processing")
		self.assertEqual(step_gate.start_cycle(su), 2)
		state = _lifecycle(su)
		self.assertEqual((state.current_cycle_no, state.status), (2, "Processing"))

	def test_start_cycle_clears_active_cycle_id(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.bind_cycle(su, "CY-261020-0001", "TR-004")
		step_gate.start_cycle(su)
		self.assertIsNone(_lifecycle(su).active_cycle_id)

	@bru("BRU-FLOW-004")
	def test_check_requires_previous_step_pass(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		block = step_gate.check(su, "T4")
		self.assertIsInstance(block, Block)
		self.assertEqual(block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(block.redo_step, "T3")
		self.assertIn("T3", block.reason)
		self.assertIn("T3", block.action)
		self.assertEqual(block.http_status, 409)
		step_gate.record(su, "T3", "Pass")
		self.assertIsNone(step_gate.check(su, "T4"))

	@bru("BRU-FLOW-004")
	def test_check_blocks_when_previous_step_failed(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.record(su, "T3", "Fail")
		# Set Unit đã sang Reprocess (cho phép T4 theo trạng thái) nhưng T3 chưa Đạt
		self.assertEqual(_lifecycle(su).status, "Reprocess")
		self.assertEqual(step_gate.check(su, "T4").code, "GATE_PREV_NOT_PASSED")

	@bru("BRU-FLOW-002")
	def test_check_rejects_status_invalid_for_station(self):
		su = make_set_unit().name
		self.assertEqual(_lifecycle(su).status, "New")
		block = step_gate.check(su, "T4")
		self.assertEqual(block.code, "STATUS_INVALID_FOR_STATION")
		self.assertEqual(block.http_status, 409)
		self.assertIn(su, block.reason)

	@bru("BRU-FLOW-002")
	def test_check_status_rule_comes_before_gate_rule(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3"))
		self.assertIsNone(step_gate.check(su, "T4"))
		# bộ đã Vô khuẩn thì không còn vào được T4 dù mọi cổng trước đạt
		for step in ("T4", "T5"):
			step_gate.record(su, step, "Pass")
		self.assertEqual(_lifecycle(su).status, "Sterile")
		self.assertEqual(step_gate.check(su, "T4").code, "STATUS_INVALID_FOR_STATION")

	def test_check_first_step_has_no_predecessor(self):
		su = make_set_unit().name
		self.assertIsNone(step_gate.check(su, "T1"))

	def test_check_rejects_unknown_step_and_unknown_set(self):
		su = make_set_unit().name
		with self.assertRaises(frappe.ValidationError):
			step_gate.check(su, "T9")
		with self.assertRaises(frappe.DoesNotExistError):
			step_gate.check("NO-SUCH-SET", "T4")

	def test_record_upserts_one_row(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		first = step_gate.record(su, "T4", "Pass")
		second = step_gate.record(su, "T4", "Pass")
		self.assertEqual(first, f"{su}-C1-T4")
		self.assertEqual(second, first)
		rows = frappe.get_all("Step Gate Result", filters={"set_unit": su, "step": "T4"})
		self.assertEqual(len(rows), 1)
		self.assertEqual(_gate(su, "T4").redo_count, 0)

	def test_record_stores_reference_station_and_actor(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		name = step_gate.record(su, "T4", "Pass", "Zone Station", "TR-004", station="TR-004")
		row = frappe.db.get_value(
			"Step Gate Result",
			name,
			["set_unit", "cycle_no", "step", "result", "ref_doctype", "ref_name", "station", "recorded_by"],
			as_dict=True,
		)
		self.assertEqual(
			row,
			{
				"set_unit": su,
				"cycle_no": 1,
				"step": "T4",
				"result": "Pass",
				"ref_doctype": "Zone Station",
				"ref_name": "TR-004",
				"station": "TR-004",
				"recorded_by": frappe.session.user,
			},
		)
		self.assertIsNotNone(frappe.db.get_value("Step Gate Result", name, "recorded_at"))

	def test_record_rejects_bad_input_and_cycle_zero(self):
		su = make_set_unit().name
		with self.assertRaises(frappe.ValidationError):
			step_gate.record(su, "T4", "Pass")  # chưa mở chu trình
		step_gate.start_cycle(su)
		with self.assertRaises(frappe.ValidationError):
			step_gate.record(su, "T9", "Pass")
		for result in ("Pending", "Maybe", None):
			with self.assertRaises(frappe.ValidationError):
				step_gate.record(su, "T4", result)
		self.assertEqual(frappe.get_all("Step Gate Result", filters={"set_unit": su}), [])

	@bru("BRU-FLOW-004")
	def test_fail_counts_redo_and_resets_later_steps(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		for step in ("T3", "T4", "T5"):
			step_gate.record(su, step, "Pass")
		self.assertEqual(_lifecycle(su).status, "Processing")
		step_gate.record(su, "T4", "Fail")
		self.assertEqual(_gate(su, "T4"), {"result": "Fail", "redo_count": 1})
		self.assertEqual(_gate(su, "T5"), {"result": "Pending", "redo_count": 0})
		self.assertEqual(_gate(su, "T3"), {"result": "Pass", "redo_count": 0})
		self.assertEqual(_lifecycle(su).status, "Reprocess")
		step_gate.record(su, "T4", "Pass")
		self.assertEqual(_gate(su, "T4"), {"result": "Pass", "redo_count": 1})
		self.assertEqual(_lifecycle(su).status, "Processing")

	@bru("BRU-FLOW-004")
	def test_fail_keeps_redo_count_of_reset_steps(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		for step in ("T3", "T4", "T5"):
			step_gate.record(su, step, "Pass")
		step_gate.record(su, "T5", "Fail")  # T5.redo_count = 1
		step_gate.record(su, "T5", "Pass")
		step_gate.record(su, "T4", "Fail")  # đặt lại T5 về Pending nhưng giữ redo_count
		self.assertEqual(_gate(su, "T5"), {"result": "Pending", "redo_count": 1})
		self.assertEqual(
			[g["result"] for g in step_gate.gates(su)], ["Pending", "Pending", "Pass", "Fail", "Pending"]
		)

	def test_all_five_pass_sets_sterile(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		for step in step_gate.STEPS[:-1]:
			step_gate.record(su, step, "Pass")
			self.assertEqual(_lifecycle(su).status, "Processing")
		step_gate.record(su, "T5", "Pass")
		self.assertEqual(_lifecycle(su).status, "Sterile")

	def test_new_cycle_gates_start_pending(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3", "T4", "T5"))
		self.assertEqual(_lifecycle(su).status, "Sterile")
		self.assertEqual(step_gate.start_cycle(su), 2)
		self.assertEqual({g["result"] for g in step_gate.gates(su)}, {"Pending"})
		# bản ghi chu trình 1 còn nguyên
		self.assertEqual(_gate(su, "T5", cycle_no=1), {"result": "Pass", "redo_count": 0})
		self.assertEqual(step_gate.check(su, "T4").code, "GATE_PREV_NOT_PASSED")

	def test_gates_lists_all_five_steps(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.record(su, "T1", "Pass")
		self.assertEqual(
			step_gate.gates(su),
			[
				{"step": "T1", "result": "Pass", "redo_count": 0},
				{"step": "T2", "result": "Pending", "redo_count": 0},
				{"step": "T3", "result": "Pending", "redo_count": 0},
				{"step": "T4", "result": "Pending", "redo_count": 0},
				{"step": "T5", "result": "Pending", "redo_count": 0},
			],
		)

	def test_gates_and_bind_require_a_started_cycle(self):
		su = make_set_unit().name
		with self.assertRaises(frappe.ValidationError):
			step_gate.gates(su)
		with self.assertRaises(frappe.ValidationError):
			step_gate.bind_cycle(su, "CY-261020-0001", "TR-004")

	def test_bind_and_release_cycle(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.bind_cycle(su, "CY-261020-0001", "TR-004")
		state = _lifecycle(su)
		self.assertEqual((state.active_cycle_id, state.current_station), ("CY-261020-0001", "TR-004"))
		step_gate.release_cycle(su)
		state = _lifecycle(su)
		self.assertIsNone(state.active_cycle_id)
		self.assertEqual(state.current_station, "TR-004")
		# release lần hai không đổi gì, không lỗi
		step_gate.release_cycle(su)
		self.assertIsNone(_lifecycle(su).active_cycle_id)

	def test_bind_cycle_keeps_station_when_none_and_rejects_blank_id(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.bind_cycle(su, "CY-261020-0001", "TR-004")
		step_gate.bind_cycle(su, "CY-261020-0002", None)
		state = _lifecycle(su)
		self.assertEqual((state.active_cycle_id, state.current_station), ("CY-261020-0002", "TR-004"))
		with self.assertRaises(frappe.ValidationError):
			step_gate.bind_cycle(su, "", "TR-004")

	def test_engine_writes_are_audited(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.record(su, "T4", "Pass")
		created = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Step Gate Result", "ref_name": f"{su}-C1-T4", "action": "Create"},
		)
		self.assertEqual(len(created), 1)
		updates = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Set Unit", "ref_name": su, "action": "Update"},
			fields=["new_value"],
		)
		new_values = [frappe.parse_json(row.new_value) for row in updates]
		self.assertTrue(
			any(v.get("current_cycle_no") == 1 and v.get("status") == "Processing" for v in new_values)
		)

	def test_lifecycle_fields_are_still_guarded_outside_the_engine(self):
		su = make_set_unit()
		step_gate.start_cycle(su.name)
		doc = frappe.get_doc("Set Unit", su.name)
		doc.current_cycle_no = 9
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value("Set Unit", su.name, "current_cycle_no"), 1)

	def test_assembly_submit_records_t3(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		record = make_assembly_record(su, "Pass")
		self.assertTrue(record.name.startswith("AS-"))
		self.assertEqual(record.cycle_no, 1)
		self.assertEqual(step_gate.gates(su)[2], {"step": "T3", "result": "Pass", "redo_count": 0})
		row = frappe.db.get_value(
			"Step Gate Result", f"{su}-C1-T3", ["ref_doctype", "ref_name"], as_dict=True
		)
		self.assertEqual(row, {"ref_doctype": "Assembly Record", "ref_name": record.name})
		self.assertIsNone(step_gate.check(su, "T4"))

	def test_assembly_fail_records_t3_fail(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		make_assembly_record(su, "Fail")
		self.assertEqual(step_gate.gates(su)[2], {"step": "T3", "result": "Fail", "redo_count": 1})
		self.assertEqual(_lifecycle(su).status, "Reprocess")
