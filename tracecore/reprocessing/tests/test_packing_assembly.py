"""T4 đóng gói bộ có dòng thiếu đã R02 xác nhận ở T3 (FEAT-020 Task 5, FR-M2-06, FR-M2-06.1)."""

from datetime import datetime, timezone

import frappe

from tracecore.core import step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import pack_label, packing
from tracecore.tests.factories import make_assembly_record, make_set_type, make_set_unit, make_t4_ready_set
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-004"
BOM = (("KC-01", 2), ("KC-02", 1))


def _utc_now():
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate(ready, confirmed=None, **overrides):
	args = {
		"set_id": ready.set_id,
		"station": STATION,
		"confirmed": list(ready.instruments if confirmed is None else confirmed),
		"ci_batch": ready.ci_batch,
		"pack_type": ready.pack_type,
		"maint_actions": [],
		"client_ts": _utc_now(),
		**overrides,
	}
	return packing.generate(**args)


class TestPackingWithConfirmedShortage(IsolatedTestCase):
	@bru("BRU-REP-003")
	def test_confirmed_shortage_line_needs_no_tick_and_is_not_recorded_as_confirmed(self):
		ready = make_t4_ready_set(short={"KC-02": 0})
		self.assertEqual(ready.instruments, ["KC-01"])
		result = _generate(ready)
		pack = frappe.get_doc("Pack", result["pack"]["cycle_id"])
		self.assertEqual([(row.instrument, row.qty) for row in pack.instruments_confirmed], [("KC-01", 2)])
		self.assertEqual(
			pack.assembly,
			frappe.get_all("Assembly Record", filters={"set_unit": ready.set_id}, pluck="name")[0],
		)
		self.assertEqual(step_gate.gates(ready.set_id)[3]["result"], "Pass")

	def test_other_lines_still_have_to_be_ticked(self):
		ready = make_t4_ready_set(short={"KC-02": 0})
		with self.assertRaises(BlockedError) as raised:
			_generate(ready, confirmed=[])
		self.assertEqual(raised.exception.block.code, "BOM_INCOMPLETE")
		self.assertEqual([item["instrument"] for item in raised.exception.block.items], ["KC-01"])

	def test_partly_missing_line_records_the_quantity_present(self):
		ready = make_t4_ready_set(short={"KC-01": 1})
		pack = frappe.get_doc("Pack", _generate(ready, confirmed=["KC-02"])["pack"]["cycle_id"])
		self.assertEqual(
			sorted((row.instrument, row.qty) for row in pack.instruments_confirmed),
			[("KC-01", 1), ("KC-02", 1)],
		)

	def test_context_lists_the_confirmed_shortage_for_the_station(self):
		ready = make_t4_ready_set(short={"KC-02": 0})
		shortage = packing.get_context(ready.set_id, STATION)["shortage"]
		self.assertEqual([(row["instrument"], row["missing_qty"]) for row in shortage], [("KC-02", 1)])
		whole = make_t4_ready_set()
		self.assertEqual(packing.get_context(whole.set_id, STATION)["shortage"], [])

	@bru("BRU-REP-003")
	def test_label_prints_the_missing_instruments(self):
		ready = make_t4_ready_set(short={"KC-02": 0})
		result = _generate(ready)
		pack = frappe.get_doc("Pack", result["pack"]["cycle_id"])
		warning = pack_label.label_context(pack)["warning"]
		self.assertTrue(warning.startswith("THIẾU: "), warning)
		self.assertIn("KC-02", warning)
		job = frappe.get_doc("Print Job", result["print"]["print_job"])
		self.assertIn("KC-02", job.payload or frappe.parse_json(job.data)["label_context"]["warning"])
		whole = make_t4_ready_set(type_code="T4WHL")
		whole_pack = frappe.get_doc("Pack", _generate(whole)["pack"]["cycle_id"])
		self.assertEqual(pack_label.label_context(whole_pack)["warning"], "")

	@bru("BRU-REP-003")
	def test_unconfirmed_shortage_keeps_t4_locked_by_the_gate(self):
		unit = make_set_unit(make_set_type("T4SHT", bom=BOM).name)
		step_gate.start_cycle(unit.name)
		step_gate.record(unit.name, "T1", "Pass")
		step_gate.record(unit.name, "T2", "Pass")
		lines = [
			{"instrument": "KC-01", "counted": 1, "actual_qty": 0},
			{"instrument": "KC-02", "counted": 1, "actual_qty": 1},
		]
		draft = make_assembly_record(unit, lines=lines, submit=False)
		with self.assertRaises(frappe.ValidationError):
			draft.submit()
		with self.assertRaises(BlockedError) as raised:
			packing.get_context(unit.name, STATION)
		self.assertEqual(raised.exception.block.code, "GATE_PREV_NOT_PASSED")
