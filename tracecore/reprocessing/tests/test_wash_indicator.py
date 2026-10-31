"""Chỉ thị rửa theo lô và trạng thái Chờ đọc chỉ thị (A-257, FR-M2-04.8 đến .10, UC-06 A5, E6)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import client_time, step_gate
from tracecore.reprocessing import assembly, machine_data, pick_list, recall, trace, washing
from tracecore.reprocessing.report.pack_trace import pack_trace
from tracecore.reprocessing.tests import test_washing_result as base
from tracecore.tests.factories import (
	make_batch,
	make_employee,
	make_item,
	make_sterilize_program,
	make_sterilizer,
	make_wash_machine,
	make_wash_program,
	make_wash_ready_set,
)
from tracecore.tests.utils import bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

INDICATOR_ITEM = "CI-RUA-TEST"
PHOTO = "/private/files/chi-thi.jpg"


class IndicatorCase(base.WashResultCase):
	def setUp(self):
		super().setUp()
		make_item(INDICATOR_ITEM, "Chemical Indicator", has_batch_no=1, ci_class="1")
		self.require()
		self.reader = make_employee()

	def require(self, photo=1, program=None):
		frappe.db.set_value(
			"Process Program",
			(program or self.program).name,
			{"requires_wash_indicator": 1, "requires_wash_indicator_photo": photo},
		)

	def unload(self, batch, employee=None, equipment_raw=None):
		return washing.unload_context(
			batch,
			self.machine.name if equipment_raw is None else equipment_raw,
			batch,
			base.STATION,
			employee=employee or self.reader.name,
			client_ts=client_time.utc_now(),
		)

	def awaiting(self, count=2):
		batch, sets = self.load(count)
		self.save_data(batch)
		self.unload(batch)
		return batch, sets

	def good(self, **kwargs):
		return {
			"item": INDICATOR_ITEM,
			"lot": "LOT-NGOAI-KHO",
			"lot_expiry": add_days(today(), 30),
			"result": "Pass",
			"photo": PHOTO,
			**kwargs,
		}

	def record(self, batch, indicator, result="Pass"):
		return self.close(
			batch, result=result, clean_test=None, indicator=indicator, unloaded_by=self.reader.name
		)

	def assert_still_awaiting(self, batch, sets):
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), washing.AWAITING)
		self.assertFalse(frappe.db.exists("Load Indicator Result", {"wash_batch": batch}))
		self.assertEqual(washing._t2_result(sets[0]), step_gate.PENDING)


class TestAwaitingResult(IndicatorCase):
	@bru("BRU-REP-016")
	def test_program_not_required_keeps_old_flow(self):
		frappe.db.set_value("Process Program", self.program.name, "requires_wash_indicator", 0)
		batch, _sets = self.load(1)
		self.assertEqual(self.unload(batch)["status"], washing.RUNNING)
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "unloaded_by"), None)
		self.save_data(batch)
		self.close(batch)
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Passed")

	@bru("BRU-REP-016")
	def test_unload_moves_batch_to_awaiting_and_frees_the_washer(self):
		batch, sets = self.load(2)
		context = self.unload(batch)
		self.assertEqual(context["status"], washing.AWAITING)
		self.assertEqual(context["indicator_required"], 1)
		self.assertEqual(context["indicator_photo_required"], 1)
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual(doc.unloaded_by, self.reader.name)
		self.assertEqual(doc.unload_scan_equipment, self.machine.name)
		self.assertTrue(doc.unload_scan_at)
		self.assertIsNone(washing.check_equipment_ready(self.machine.name))
		self.assertEqual(washing._t2_result(sets[0]), step_gate.PENDING)

	def test_unload_again_keeps_first_unloader(self):
		batch, _sets = self.awaiting(1)
		self.unload(batch, employee=make_employee().name)
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "unloaded_by"), self.reader.name)

	@bru("BRU-FLOW-004")
	def test_sets_of_awaiting_batch_are_blocked_at_t3_by_the_server(self):
		_batch, sets = self.awaiting(1)
		self.assertEqual(base._code(assembly.open_set, sets[0], base.CLEAN_STATION), "GATE_PREV_NOT_PASSED")
		self.assertNotIn(sets[0], [row["id"] for row in pick_list.suggest("T3")["items"]])

	def test_sets_of_awaiting_batch_stay_out_of_the_load_screen(self):
		_batch, sets = self.awaiting(1)
		other = make_wash_machine(has_printout=1)
		self.assertEqual(base._code(washing.admit_set, sets[0], other.name), "SET_IN_OTHER_BATCH")
		self.assertNotIn(sets[0], [row.set_id for row in washing.waiting_sets()])
		self.assertNotIn(sets[0], [row["id"] for row in pick_list.suggest("T2")["items"]])

	def test_awaiting_batches_are_listed_apart_from_running(self):
		batch, _sets = self.awaiting(1)
		self.assertIn(batch, [row["batch"] for row in washing.awaiting_batches()])
		self.assertNotIn(batch, [row["batch"] for row in washing.running_batches()])

	def test_read_later_needs_only_the_batch_qr(self):
		batch, _sets = self.awaiting(1)
		self.assertEqual(
			washing.scan_unload(batch, batch, base.STATION),
			{"ok": True, "kind": "wash_batch", "awaiting": True},
		)
		self.assertEqual(self.unload(batch, equipment_raw="")["batch"], batch)

	def test_batch_qr_is_still_needed_when_reading_later(self):
		batch, _sets = self.awaiting(1)
		with self.assertRaises(washing.BlockedError):
			washing.unload_context(batch, self.machine.name, "", base.STATION)

	def test_config_snapshot_survives_switching_the_program_off(self):
		batch, sets = self.awaiting(1)
		frappe.db.set_value("Process Program", self.program.name, "requires_wash_indicator", 0)
		self.assertEqual(base._code(self.close, batch), "INDICATOR_REQUIRED")
		self.assert_still_awaiting(batch, sets)

	def test_machine_data_still_attaches_while_awaiting(self):
		batch, _sets = self.awaiting(1)
		rows = machine_data._open_docs(machine_data.WASH, self.machine.name)
		self.assertIn(batch, [row.name for row in rows])


class TestIndicatorRules(IndicatorCase):
	@bru("BRU-REP-002")
	def test_pass_with_full_indicator_closes_batch_and_opens_t3(self):
		batch, sets = self.awaiting(2)
		response = self.record(batch, self.good())
		self.assertEqual(response["result"], "Pass")
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual((doc.status, doc.docstatus), ("Passed", 1))
		self.assertEqual(doc.clean_test_result, "Pass")
		for set_id in sets:
			self.assertEqual(washing._t2_result(set_id), "Pass")
		self.assertIn(sets[0], [row["id"] for row in pick_list.suggest("T3")["items"]])
		row = frappe.get_doc("Load Indicator Result", {"wash_batch": batch})
		self.assertEqual(row.indicator, "wash_indicator")
		self.assertEqual(
			(row.indicator_item, row.lot, row.result, row.photo, row.read_by, row.station),
			(INDICATOR_ITEM, "LOT-NGOAI-KHO", "Pass", PHOTO, self.reader.name, base.STATION),
		)
		self.assertTrue(row.read_at)
		self.assertEqual(getdate(row.lot_expiry), getdate(add_days(today(), 30)))

	@bru("BRU-REP-002")
	def test_pass_needs_an_indicator_even_from_running(self):
		batch, sets = self.load(1)
		self.save_data(batch)
		self.assertEqual(base._code(self.close, batch), "INDICATOR_REQUIRED")
		self.assertEqual(washing._t2_result(sets[0]), step_gate.PENDING)

	@bru("BRU-REP-002")
	def test_expired_indicator_is_blocked(self):
		batch, sets = self.awaiting(1)
		code = base._code(self.record, batch, self.good(lot_expiry=add_days(today(), -1)))
		self.assertEqual(code, "INDICATOR_EXPIRED")
		self.assert_still_awaiting(batch, sets)

	def test_indicator_expiring_on_the_day_the_batch_ran_is_valid(self):
		batch, _sets = self.awaiting(1)
		started = getdate(frappe.db.get_value("Wash Batch", batch, "started_at"))
		self.record(batch, self.good(lot_expiry=started))
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Passed")

	@bru("BRU-REP-002")
	def test_missing_lot_or_expiry_or_item_is_blocked(self):
		batch, sets = self.awaiting(1)
		for missing in (
			{"lot": " "},
			{"lot_expiry": None},
			{"lot_expiry": "khong-phai-ngay"},
			{"item": None},
		):
			code = base._code(self.record, batch, self.good(**missing))
			self.assertEqual(code, "INDICATOR_LOT_MISSING", msg=missing)
		self.assert_still_awaiting(batch, sets)

	def test_photo_only_needed_when_the_program_asks_for_it(self):
		batch, sets = self.awaiting(1)
		self.assertEqual(base._code(self.record, batch, self.good(photo=None)), "INDICATOR_PHOTO_MISSING")
		self.assert_still_awaiting(batch, sets)
		self.require(photo=0)
		other, _ = self.load(1, machine=self.spare(), program=self.spare_program)
		self.save_data(other, machine=self.spare_machine)
		self.unload_spare(other)
		self.close(
			other,
			machine=self.spare_machine,
			clean_test=None,
			indicator=self.good(photo=None),
		)
		self.assertEqual(frappe.db.get_value("Wash Batch", other, "status"), "Passed")

	def spare(self):
		self.spare_machine = make_wash_machine(has_printout=1)
		self.spare_program = make_wash_program(
			self.spare_machine.name, chemical=base.CHEMICAL, parameters=base.PARAMETERS
		)
		self.require(photo=0, program=self.spare_program)
		return self.spare_machine

	def unload_spare(self, batch):
		washing.unload_context(batch, self.spare_machine.name, batch, base.STATION)

	def test_lot_in_erpnext_decides_the_expiry(self):
		make_batch(INDICATOR_ITEM, "CI-LOT-CU", add_days(today(), -10))
		batch, sets = self.awaiting(1)
		code = base._code(self.record, batch, self.good(lot="CI-LOT-CU", lot_expiry=add_days(today(), 100)))
		self.assertEqual(code, "INDICATOR_EXPIRED")
		self.assert_still_awaiting(batch, sets)

	def test_lot_of_another_item_is_blocked(self):
		make_item("CI-RUA-KHAC", "Chemical Indicator", has_batch_no=1, ci_class="1")
		make_batch("CI-RUA-KHAC", "CI-LOT-KHAC", add_days(today(), 100))
		batch, _sets = self.awaiting(1)
		code = base._code(self.record, batch, self.good(lot="CI-LOT-KHAC"))
		self.assertEqual(code, "INDICATOR_LOT_INVALID")

	def test_bad_indicator_result_is_rejected(self):
		batch, sets = self.awaiting(1)
		self.assertEqual(base._code(self.record, batch, self.good(result="Maybe")), "RESULT_INVALID")
		self.assert_still_awaiting(batch, sets)

	@bru("BRU-REP-002")
	def test_fail_sends_sets_back_and_raises_nc_without_lot_or_photo(self):
		batch, sets = self.awaiting(2)
		response = self.record(batch, {"result": "Fail"})
		self.assertEqual(response["result"], "Fail")
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual((doc.status, doc.cycle_result, doc.clean_test_result), ("Failed", "Fail", "Fail"))
		self.assertEqual(doc.nc_pending, 1)
		for set_id in sets:
			self.assertEqual(frappe.db.get_value("Set Unit", set_id, "status"), "Reprocess")
		self.assertTrue(response["incident_id"])
		self.assertIn(sets[0], [row["set_id"] for row in washing.redo_queue()])
		self.assertEqual(
			frappe.db.get_value("Load Indicator Result", {"wash_batch": batch}, "result"), "Fail"
		)

	def test_cycle_fail_with_indicator_pass_fails_the_batch(self):
		batch, _sets = self.awaiting(1)
		self.assertEqual(self.record(batch, self.good(), result="Fail")["result"], "Fail")
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Failed")

	def test_closed_batch_cannot_be_recorded_again(self):
		batch, _sets = self.awaiting(1)
		self.record(batch, self.good())
		self.assertEqual(base._code(self.record, batch, self.good()), "BATCH_NOT_RUNNING")


class TestIndicatorLookup(IndicatorCase):
	def test_lot_in_erpnext_fills_item_and_expiry(self):
		expiry = add_days(today(), 90)
		make_batch(INDICATOR_ITEM, "CI-LOT-MOI", expiry)
		found = washing.indicator_lot(" CI-LOT-MOI\r\n")
		self.assertTrue(found["found"])
		self.assertEqual((found["lot"], found["item"]), ("CI-LOT-MOI", INDICATOR_ITEM))
		self.assertEqual(getdate(found["expiry_date"]), getdate(expiry))

	def test_unknown_lot_is_typed_by_hand(self):
		self.assertEqual(washing.indicator_lot("KHONG-CO"), {"found": False, "lot": "KHONG-CO"})

	def test_context_lists_indicator_items_only_when_required(self):
		batch, _sets = self.load(1)
		context = self.unload(batch)
		self.assertIn(INDICATOR_ITEM, [row["item"] for row in context["indicator_items"]])
		self.assertIsNone(context["indicator"])


class TestIndicatorTrace(IndicatorCase):
	@bru("BRU-REP-016")
	def test_set_id_shows_batch_indicator_lot_photo_and_reader(self):
		batch, sets = self.awaiting(1)
		self.record(batch, self.good())
		event = next(row for row in trace.query(set_id=sets[0])["chains"][0]["events"] if row["step"] == "T2")
		self.assertEqual(event["ref_name"], batch)
		indicator = event["indicator"]
		self.assertEqual(
			(indicator["item"], indicator["lot"], indicator["result"], indicator["photo"]),
			(INDICATOR_ITEM, "LOT-NGOAI-KHO", "Pass", PHOTO),
		)
		self.assertEqual(indicator["read_by"], self.reader.name)
		self.assertTrue(indicator["read_at"])
		self.assertEqual(washing.lookup(batch)["indicator"]["lot"], "LOT-NGOAI-KHO")

	def test_pack_trace_report_has_indicator_columns(self):
		batch, sets = self.awaiting(1)
		self.record(batch, self.good())
		columns, rows, _message = pack_trace.execute({"set_id": sets[0]})
		self.assertTrue({"wash_indicator", "indicator_photo"} <= {c["fieldname"] for c in columns})
		row = next(row for row in rows if row["ref_name"] == batch)
		self.assertIn("LOT-NGOAI-KHO", row["wash_indicator"])
		self.assertEqual(row["indicator_photo"], PHOTO)

	def test_recall_line_text_shows_the_wash_indicator(self):
		batch, sets = self.awaiting(1)
		self.record(batch, self.good())
		cycle = frappe.db.get_value("Set Unit", sets[0], "current_cycle_no")
		self.assertIn("LOT-NGOAI-KHO", trace.wash_indicator_text(sets[0], cycle))
		self.assertEqual(trace.wash_indicator_text(make_wash_ready_set().name, 1), None)

	def test_recall_by_lot_ignores_wash_indicators(self):
		batch, _sets = self.awaiting(1)
		self.record(batch, self.good())
		self.assertEqual(recall._loads_of_lot("LOT-NGOAI-KHO"), [])


class TestProgramConfig(IndicatorCase):
	def test_defaults_are_off(self):
		machine = make_wash_machine()
		program = make_wash_program(machine.name)
		self.assertEqual(program.requires_wash_indicator, 0)
		self.assertEqual(program.requires_wash_indicator_photo, 0)

	def test_sterilizer_program_cannot_require_a_wash_indicator(self):
		program = make_sterilize_program(
			make_sterilizer().name, requires_wash_indicator=1, requires_wash_indicator_photo=1
		)
		self.assertEqual(program.requires_wash_indicator, 0)
		self.assertEqual(program.requires_wash_indicator_photo, 0)

	def test_photo_cannot_be_required_without_the_indicator(self):
		program = make_wash_program(
			make_wash_machine().name, requires_wash_indicator=0, requires_wash_indicator_photo=1
		)
		self.assertEqual(program.requires_wash_indicator_photo, 0)
