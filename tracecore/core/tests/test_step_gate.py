import subprocess  # nosec B404 - chạy lint kiến trúc của repo
import sys
from functools import partial
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import step_gate, zones
from tracecore.core.errors import Block, BlockedError
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

	def test_start_cycle_pins_bom_version_from_hook_in_same_save(self):
		su = make_set_unit().name
		with patch("tracecore.core.step_gate.extension.run", return_value=["x", True, 4, 9]) as run:
			self.assertEqual(step_gate.start_cycle(su, on="2026-11-02"), 1)
		bom_calls = [c for c in run.call_args_list if c.args[0] == "tracecore_cycle_bom_version"]
		self.assertEqual(len(bom_calls), 1)
		hook, ctx = bom_calls[0].args
		self.assertEqual(hook, "tracecore_cycle_bom_version")
		set_type = frappe.db.get_value("Set Unit", su, "set_type")
		self.assertEqual(ctx, {"set_unit": su, "set_type": set_type, "cycle_no": 1, "on": "2026-11-02"})
		self.assertEqual(frappe.db.get_value("Set Unit", su, "cycle_bom_version"), 4)  # số nguyên đầu tiên
		# một lần lưu vòng đời: cùng một Audit Update mang chu trình, trạng thái và phiên bản ghim
		updates = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Set Unit", "ref_name": su, "action": "Update"},
			fields=["new_value"],
		)
		self.assertEqual(len(updates), 1)
		new = frappe.parse_json(updates[0].new_value)
		self.assertEqual(
			(new.get("current_cycle_no"), new.get("status"), new.get("cycle_bom_version")),
			(1, "Processing", 4),
		)

		# không có kết quả nguyên → 0 (bỏ ghim của chu trình trước); `on` mặc định = giờ server
		with patch("tracecore.core.step_gate.extension.run", return_value=[]) as run:
			self.assertEqual(step_gate.start_cycle(su), 2)
		self.assertIsNotNone(run.call_args.args[1]["on"])
		self.assertEqual(frappe.db.get_value("Set Unit", su, "cycle_bom_version"), 0)

	def test_start_cycle_clears_active_cycle_id(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.bind_cycle(su, "CY-261020-0001", "TR-004")
		step_gate.start_cycle(su)
		self.assertIsNone(_lifecycle(su).active_cycle_id)

	def test_init_unit_is_only_lifecycle_writer(self):
		# FEAT-016 G4: khởi tạo trường vòng đời của bộ mới cũng chỉ ở step gate (ADR-005)
		self.assertEqual(
			step_gate.LIFECYCLE_DEFAULTS,
			{
				"status": "New",
				"cycles_used": 0,
				"current_station": None,
				"active_cycle_id": None,
				"current_cycle_no": 0,
				"cycle_bom_version": 0,
			},
		)
		doc = frappe.new_doc("Set Unit")
		doc.update(
			{"status": "Sterile", "current_cycle_no": 4, "active_cycle_id": "CY-1", "cycle_bom_version": 3}
		)
		step_gate.init_unit(doc, 7)
		self.assertEqual(
			{field: doc.get(field) for field in step_gate.LIFECYCLE_DEFAULTS},
			{**step_gate.LIFECYCLE_DEFAULTS, "cycles_used": 7},
		)
		self.assertTrue(doc.flags.tc_step_gate)
		self.assertEqual(doc.flags.tc_audit_reason, "issue")
		existing = frappe.get_doc("Set Unit", make_set_unit().name)
		with self.assertRaises(frappe.ValidationError):
			step_gate.init_unit(existing)
		for bad in (-1, "3", True, None):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				step_gate.init_unit(frappe.new_doc("Set Unit"), bad)

		# doc mới qua đường cấp nhưng không qua init_unit: trường vòng đời về mặc định
		set_type = frappe.db.get_value("Set Unit", existing.name, "set_type")
		bare = frappe.get_doc(
			{"doctype": "Set Unit", "set_type": set_type, "max_cycles": 10, "status": "Sterile"}
		)
		bare.flags.tc_set_issue = True
		bare.insert()
		self.assertEqual(_lifecycle(bare.name).status, "New")

		lint = subprocess.run(  # nosec B603 - đối số cố định
			[sys.executable, frappe.get_app_path("tracecore", "..", "scripts", "check_architecture.py")],
			capture_output=True,
			text=True,
			check=False,
		)
		self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
		self.assertNotIn("R2", lint.stdout)

	def test_lifecycle_events_recorded_as_audit_reason(self):
		# FEAT-016 G13: Audit Log của Set Unit thành lịch sử vòng đời (sự kiện ở cột reason)
		su = make_set_unit().name

		def reasons():
			return frappe.get_all(
				"Audit Log",
				filters={"ref_doctype": "Set Unit", "ref_name": su, "action": "Update"},
				pluck="reason",
				order_by="creation asc, name asc",
			)

		step_gate.start_cycle(su)
		self.assertEqual(reasons(), ["start_cycle"])
		step_gate.record(su, "T4", "Fail")
		self.assertEqual(reasons()[-1], "gate T4 Fail")
		step_gate.record(su, "T4", "Pass")
		self.assertEqual(reasons()[-1], "gate T4 Pass")
		step_gate.bind_cycle(su, "CY-261022-0001", "TR-004")
		self.assertEqual(reasons()[-1], "bind_cycle")
		step_gate.release_cycle(su)
		self.assertEqual(
			reasons(), ["start_cycle", "gate T4 Fail", "gate T4 Pass", "bind_cycle", "release_cycle"]
		)

	@bru("BRU-FLOW-004")
	def test_check_requires_previous_step_pass(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		block = step_gate.check(su, "T4")
		self.assertIsInstance(block, Block)
		self.assertEqual(block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(block.redo_step, "T3")
		self.assertIn(zones.gate_label("T3"), block.reason)
		self.assertIn(zones.gate_label("T3"), block.action)
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

	@bru("BRU-FLOW-002")
	def test_check_t1_accepts_new_at_department_and_awaiting_receipt_only(self):
		# FEAT-019, FR-M2-02: T1 chỉ nhận bộ Mới tạo, Tại khoa, Chờ tiếp nhận
		self.assertEqual(step_gate.STATION_STATUSES["T1"], ("New", "At Department", "Awaiting Receipt"))
		for status in ("New", "At Department", "Awaiting Receipt"):
			su = make_set_unit().name
			frappe.db.set_value("Set Unit", su, "status", status)
			self.assertIsNone(step_gate.check(su, "T1"), status)
		for status in ("Processing", "Reprocess", "Sterile", "Disposed"):
			su = make_set_unit().name
			frappe.db.set_value("Set Unit", su, "status", status)
			self.assertEqual(step_gate.check(su, "T1").code, "STATUS_INVALID_FOR_STATION", status)

	@bru("BRU-FLOW-004")
	def test_check_t2_requires_t1_pass(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		block = step_gate.check(su, "T2")
		self.assertEqual(block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(block.redo_step, "T1")
		step_gate.record(su, "T1", "Pass")
		self.assertIsNone(step_gate.check(su, "T2"))

	@bru("BRU-FLOW-002")
	def test_check_t2_rejects_status_invalid_for_station(self):
		sterile = make_set_unit().name
		make_cycle(sterile, passed=("T1", "T2", "T3", "T4", "T5"))
		self.assertEqual(_lifecycle(sterile).status, "Sterile")
		self.assertEqual(step_gate.check(sterile, "T2").code, "STATUS_INVALID_FOR_STATION")
		# bộ mới tạo, chưa mở chu trình, cũng không vào được T2
		self.assertEqual(step_gate.check(make_set_unit().name, "T2").code, "STATUS_INVALID_FOR_STATION")

	def test_check_t2_accepts_set_in_reprocess(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1",))
		step_gate.record(su, "T2", "Fail")
		self.assertEqual(_lifecycle(su).status, "Reprocess")
		self.assertIsNone(step_gate.check(su, "T2"))

	@bru("BRU-FLOW-004")
	def test_check_t5_requires_t4_pass(self):
		su = make_set_unit().name
		make_cycle(su, passed=("T1", "T2", "T3"))
		block = step_gate.check(su, "T5")
		self.assertEqual(block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(block.redo_step, "T4")
		step_gate.record(su, "T4", "Pass")
		self.assertIsNone(step_gate.check(su, "T5"))

	@bru("BRU-FLOW-002")
	def test_check_t5_rejects_status_invalid_for_station(self):
		sterile = make_set_unit().name
		make_cycle(sterile, passed=("T1", "T2", "T3", "T4", "T5"))
		self.assertEqual(step_gate.check(sterile, "T5").code, "STATUS_INVALID_FOR_STATION")
		self.assertEqual(step_gate.STATION_STATUSES["T5"], ("Processing", "Reprocess"))

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

	def test_gate_recorded_at_uses_client_ts(self):
		"""FR-M1-06.4 (A-40 D6): thời điểm cổng = thời điểm nghiệp vụ ở trạm, kể cả khi đồng bộ muộn."""
		from datetime import datetime

		from frappe.utils import get_datetime

		from tracecore.core.client_time import to_system_time

		su = make_set_unit().name
		step_gate.start_cycle(su)
		client_ts = datetime(2026, 10, 25, 16, 30)  # UTC = 23:30 giờ hệ thống
		name = step_gate.record(su, "T1", "Pass", station="TR-001", client_ts=client_ts)
		recorded = get_datetime(frappe.db.get_value("Step Gate Result", name, "recorded_at"))
		self.assertEqual(recorded, to_system_time(client_ts))

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
		doc = frappe.get_doc("Set Unit", su.name)
		doc.cycle_bom_version = 9
		with self.assertRaises(frappe.ValidationError):
			doc.save()

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


class TestStepGateEndOfLife(FrappeTestCase):
	"""FEAT-032 (A-18 Q3, Q4): bộ vượt cơ số → Hết vòng đời; ghi đè được duyệt → mở lại."""

	def _ready(self):
		su = make_set_unit().name
		make_cycle(su)  # T1..T3 Đạt, Processing
		return su

	@bru("BRU-PAR-002")
	def test_end_of_life_sets_status_keeps_cycle_and_audits_reason(self):
		su = self._ready()
		self.assertTrue(step_gate.end_of_life(su, "Par Exceeded"))
		state = _lifecycle(su)
		self.assertEqual((state.status, state.current_cycle_no), ("End of Life", 1))
		row = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Set Unit", "ref_name": su, "action": "Update", "reason": "Par Exceeded"},
			fields=["old_value", "new_value"],
		)
		self.assertEqual(len(row), 1)
		self.assertEqual(frappe.parse_json(row[0].old_value).get("status"), "Processing")
		self.assertEqual(frappe.parse_json(row[0].new_value).get("status"), "End of Life")

	def test_end_of_life_is_idempotent_and_drops_active_cycle_id(self):
		su = self._ready()
		step_gate.bind_cycle(su, "CY-261023-0001", "TR-004")
		self.assertTrue(step_gate.end_of_life(su))
		self.assertIsNone(_lifecycle(su).active_cycle_id)
		self.assertFalse(step_gate.end_of_life(su))  # đã Hết vòng đời: không ghi lại
		updates = frappe.db.count(
			"Audit Log", {"ref_doctype": "Set Unit", "ref_name": su, "reason": "Par Exceeded"}
		)
		self.assertEqual(updates, 0)  # lý do mặc định None

	def test_end_of_life_refuses_disposed_set(self):
		su = self._ready()
		frappe.db.set_value("Set Unit", su, "status", "Disposed")
		with self.assertRaises(frappe.ValidationError):
			step_gate.end_of_life(su)

	@bru("BRU-PAR-002")
	def test_check_blocks_end_of_life_at_every_step(self):
		su = self._ready()
		step_gate.end_of_life(su)
		for step in step_gate.STEPS:
			block = step_gate.check(su, step)
			self.assertEqual(block.code, "SET_END_OF_LIFE", msg=step)
			self.assertEqual(block.http_status, 409)
			self.assertIn(su, block.reason)
			self.assertTrue(block.title and block.action)
		self.assertEqual(step_gate.check(su, "T4", for_update=True).code, "SET_END_OF_LIFE")

	@bru("BRU-PAR-004")
	def test_reopen_after_override_only_from_end_of_life(self):
		su = self._ready()
		with self.assertRaises(frappe.ValidationError):
			step_gate.reopen_after_override(su, "GD-2026-00001")
		step_gate.end_of_life(su)
		step_gate.reopen_after_override(su, "GD-2026-00001")
		self.assertEqual(_lifecycle(su).status, "Processing")
		self.assertIsNone(step_gate.check(su, "T4"))  # cổng chu trình hiện hành giữ nguyên
		reasons = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Set Unit", "ref_name": su, "action": "Update"},
			pluck="reason",
		)
		self.assertIn("GD-2026-00001", reasons)


class TestStepGateLocking(FrappeTestCase):
	"""record() chạy dưới REPEATABLE READ: sau khi khóa Set Unit, mọi thứ nó quyết định phải đọc có khóa.

	Đọc thường dùng snapshot cũ (đã mở bởi @idempotent trước khi gọi hàm), không thấy dòng vừa commit của request
	song song cùng bộ. Không cần kết nối thứ hai: kiểm tra các câu SQL thực sự phát ra.
	"""

	def _capture(self, fn, *args):
		queries = []
		real_sql = frappe.db.sql

		def spy(query, *a, **kw):
			queries.append(" ".join(str(query).split()) + f" {a} {kw}")
			return real_sql(query, *a, **kw)

		with patch.object(frappe.db, "sql", spy):
			fn(*args)
		return queries

	def _selects_on(self, queries, doctype):
		table = f"`tab{doctype}`".lower()
		return [q for q in queries if q.lower().startswith("select") and table in q.lower()]

	def _assert_gate_reads_are_locking(self, queries):
		reads = self._selects_on(queries, "Step Gate Result")
		self.assertTrue(reads, msg="record() không đọc Step Gate Result nào?")
		plain = [q for q in reads if "for update" not in q.lower()]
		self.assertFalse(plain, msg=f"Đọc thường trên Step Gate Result: {plain}")
		# khóa theo khóa chính từng dòng: IN(...)/lọc theo cột không chỉ mục khóa khoảng hoặc cả bảng,
		# khiến hai bộ khác nhau chặn hoặc deadlock lẫn nhau
		ranged = [q for q in reads if " in (" in q.lower() or "set_unit" in q.lower()]
		self.assertFalse(ranged, msg=f"Đọc có khóa theo khoảng/cột: {ranged}")

	def test_record_locks_set_unit_before_reading_gate_rows(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		queries = self._capture(step_gate.record, su, "T4", "Pass")
		unit_reads = self._selects_on(queries, "Set Unit")
		self.assertIn("for update", unit_reads[0].lower())
		first_gate_read = next(
			i for i, q in enumerate(queries) if q in self._selects_on(queries, "Step Gate Result")
		)
		self.assertLess(queries.index(unit_reads[0]), first_gate_read)

	def test_record_new_row_reads_gate_state_with_locking_reads(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.record(su, "T3", "Pass")
		queries = self._capture(step_gate.record, su, "T4", "Pass")
		self._assert_gate_reads_are_locking(queries)
		# đủ năm bước của chu trình đều được đọc có khóa (quyết định Sterile/đặt lại cần cả năm)
		locked = " ".join(self._selects_on(queries, "Step Gate Result"))
		for step in step_gate.STEPS:
			self.assertIn(f"{su}-C1-{step}", locked)

	@bru("BRU-FLOW-004")
	def test_record_existing_row_and_reset_read_gate_state_with_locking_reads(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		for step in ("T3", "T4", "T5"):
			step_gate.record(su, step, "Pass")
		queries = self._capture(step_gate.record, su, "T4", "Fail")
		self._assert_gate_reads_are_locking(queries)
		self.assertEqual(_gate(su, "T5"), {"result": "Pending", "redo_count": 0})

	def test_check_for_update_reads_state_and_gates_with_locking_reads(self):
		# packing.generate gọi check(for_update=True) sau khi khóa Set Unit: snapshot REPEATABLE READ có thể cũ
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.record(su, "T3", "Pass")
		queries = self._capture(partial(step_gate.check, for_update=True), su, "T4")
		unit_reads = self._selects_on(queries, "Set Unit")
		self.assertTrue(unit_reads)
		self.assertFalse([q for q in unit_reads if "for update" not in q.lower()])
		self._assert_gate_reads_are_locking(queries)
		self.assertIn(f"{su}-C1-T3", " ".join(self._selects_on(queries, "Step Gate Result")))

	@bru("BRU-FLOW-004")
	def test_check_for_update_gives_the_same_answers(self):
		su = make_set_unit().name
		self.assertEqual(step_gate.check(su, "T4", for_update=True).code, "STATUS_INVALID_FOR_STATION")
		step_gate.start_cycle(su)
		self.assertEqual(step_gate.check(su, "T4", for_update=True).code, "GATE_PREV_NOT_PASSED")
		step_gate.record(su, "T3", "Pass")
		self.assertIsNone(step_gate.check(su, "T4", for_update=True))
		# FEAT-019: T1 chỉ nhận bộ chưa vào chu trình / đã trở về; bộ đang xử lý bị chặn, bộ mới thì qua
		self.assertEqual(step_gate.check(su, "T1", for_update=True).code, "STATUS_INVALID_FOR_STATION")
		self.assertIsNone(step_gate.check(make_set_unit().name, "T1", for_update=True))
		with self.assertRaises(frappe.DoesNotExistError):
			step_gate.check("NO-SUCH-SET", "T4", for_update=True)

	def test_check_default_keeps_plain_reads(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.record(su, "T3", "Pass")
		queries = self._capture(step_gate.check, su, "T4")
		self.assertTrue(self._selects_on(queries, "Set Unit"))
		self.assertTrue(self._selects_on(queries, "Step Gate Result"))
		self.assertFalse([q for q in queries if "for update" in q.lower()])

	def test_gates_display_keeps_plain_reads(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.record(su, "T3", "Pass")
		queries = self._capture(step_gate.gates, su)
		self.assertTrue(self._selects_on(queries, "Step Gate Result"))
		self.assertFalse([q for q in queries if "for update" in q.lower()])


class TestAfterSetStatusHook(FrappeTestCase):
	"""A-13 G13: ``tracecore_after_set_status`` chỉ chạy khi ``status`` thực sự đổi, payload tối thiểu cố định."""

	def _hook_calls(self, run):
		return [call.args[1] for call in run.call_args_list if call.args[0] == step_gate.STATUS_HOOK]

	def test_hook_name_is_declared(self):
		self.assertEqual(step_gate.STATUS_HOOK, "tracecore_after_set_status")
		# FEAT-017 A-38 e: M2 hủy gói còn trong kho khi bộ mượn trả hãng
		self.assertEqual(
			frappe.get_hooks("tracecore_after_set_status"), ["tracecore.reprocessing.storage.on_set_status"]
		)

	def test_start_cycle_fires_hook_once_with_payload(self):
		su = make_set_unit().name
		with patch("tracecore.core.step_gate.extension.run", return_value=[]) as run:
			step_gate.start_cycle(su, client_ts="2026-10-24T08:00:00+07:00")
		self.assertEqual(
			self._hook_calls(run),
			[
				{
					"set_unit": su,
					"old_status": "New",
					"new_status": "Processing",
					"event": "start_cycle",
					"client_ts": "2026-10-24T08:00:00+07:00",
					"ref_doctype": None,
					"ref_name": None,
				}
			],
		)

	def test_no_hook_when_status_unchanged(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		with patch("tracecore.core.step_gate.extension.run", return_value=[]) as run:
			step_gate.bind_cycle(su, "CY-261020-0001", "TR-004")  # đổi Cycle ID/trạm, không đổi status
			step_gate.record(su, "T1", "Pass")  # Processing -> Processing
			step_gate.release_cycle(su)
		self.assertEqual(self._hook_calls(run), [])

	def test_gate_fail_reports_business_reference(self):
		su = make_set_unit().name
		set_type = frappe.db.get_value("Set Unit", su, "set_type")
		step_gate.start_cycle(su)
		with patch("tracecore.core.step_gate.extension.run", return_value=[]) as run:
			step_gate.record(
				su,
				"T2",
				"Fail",
				ref_doctype="Instrument Set Type",
				ref_name=set_type,
				client_ts="2026-10-24T09:00:00+07:00",
			)
		(payload,) = self._hook_calls(run)
		self.assertEqual(
			(payload["old_status"], payload["new_status"], payload["event"]),
			("Processing", "Reprocess", "gate T2 Fail"),
		)
		self.assertEqual((payload["ref_doctype"], payload["ref_name"]), ("Instrument Set Type", set_type))
		self.assertEqual(payload["client_ts"], "2026-10-24T09:00:00+07:00")
